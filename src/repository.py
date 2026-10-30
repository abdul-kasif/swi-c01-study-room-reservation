from datetime import datetime
from sqlalchemy import Boolean, create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from src.domain import ReservationEntity, ResourceEntity

SQLALCHEMY_DATABASE_URL = "sqlite:///./reservation.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ReservationModel(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(String, index=True)
    user_id = Column(String, index=True)
    start_time = Column(DateTime, index=True)
    end_time = Column(DateTime)
    state = Column(String)


class ResourceModel(Base):
    __tablename__ = "resources"
    resource_id = Column(String, primary_key=True, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)


Base.metadata.create_all(bind=engine)

# C05: compare-and-set transition. One statement = one atomic step under
# SQLite's write lock, so "check no overlap" and "write new state" cannot be
# separated by another writer (BR-02 / REQ-04).
_TRANSITION_SQL = """
UPDATE reservations
   SET state = :new_state
 WHERE id = :id
   AND state = :expected_state
"""

_CLEANUP_SQL = """
UPDATE reservations
   SET state = 'CANCELLED'
 WHERE state IN ('DRAFT', 'PENDING_APPROVAL')
   AND start_time <= :now
"""

_NO_OVERLAP_GUARD = """
   AND NOT EXISTS (
        SELECT 1 FROM reservations o
         WHERE o.resource_id = reservations.resource_id
           AND o.state = 'CONFIRMED'
           AND o.id != reservations.id
           AND o.start_time < reservations.end_time
           AND o.end_time > reservations.start_time
   )
"""


class ReservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_resource(self, resource_id: str) -> ResourceEntity | None:
        model = (
            self.db.query(ResourceModel)
            .filter(ResourceModel.resource_id == resource_id)
            .first()
        )
        if model:
            return ResourceEntity(
                resource_id=model.resource_id,
                name=model.name,
                is_active=model.is_active,
            )
        return None

    @staticmethod
    def _to_entity(model: ReservationModel) -> ReservationEntity:
        return ReservationEntity(
            id=model.id,
            resource_id=model.resource_id,
            user_id=model.user_id,
            start_time=model.start_time,
            end_time=model.end_time,
            state=model.state,
        )

    def get_by_id(self, reservation_id: int) -> ReservationEntity | None:
        # populate_existing: always read the committed row, never a stale
        # object cached in this Session's identity map.
        model = (
            self.db.query(ReservationModel)
            .populate_existing()
            .filter(ReservationModel.id == reservation_id)
            .first()
        )
        return self._to_entity(model) if model else None

    def get_active_for_user_on_day(
        self, user_id: str, day_start: datetime, day_end: datetime
    ) -> list[ReservationEntity]:
        models = (
            self.db.query(ReservationModel)
            .filter(
                ReservationModel.user_id == user_id,
                ReservationModel.start_time >= day_start,
                ReservationModel.start_time < day_end,
                ReservationModel.state != "CANCELLED",
            )
            .all()
        )
        return [self._to_entity(m) for m in models]

    def has_confirmed_overlap(
        self,
        resource_id: str,
        start_time: datetime,
        end_time: datetime,
        exclude_id: int | None = None,
    ) -> bool:
        """Advisory check: does a confirmed reservation overlap the interval?"""
        query = self.db.query(ReservationModel).filter(
            ReservationModel.resource_id == resource_id,
            ReservationModel.state == "CONFIRMED",
            ReservationModel.start_time < end_time,
            ReservationModel.end_time > start_time,
        )

        if exclude_id is not None:
            query = query.filter(ReservationModel.id != exclude_id)

        return query.first() is not None

    def create(self, entity: ReservationEntity) -> ReservationEntity:
        model = ReservationModel(
            resource_id=entity.resource_id,
            user_id=entity.user_id,
            start_time=entity.start_time,
            end_time=entity.end_time,
            state=entity.state,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def save(self, entity: ReservationEntity) -> ReservationEntity:
        model = (
            self.db.query(ReservationModel)
            .filter(ReservationModel.id == entity.id)
            .first()
        )
        model.state = entity.state
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def cleanup_expired(self, now: datetime) -> int:
        """Atomically cancel all DRAFT and PENDING_APPROVAL reservations whose start_time has passed."""
        result = self.db.execute(text(_CLEANUP_SQL), {"now": now})
        self.db.commit()
        return result.rowcount

    def try_transition(
        self,
        reservation_id: int,
        expected_state: str,
        new_state: str,
        enforce_no_overlap: bool,
    ) -> bool:
        """
        Atomically move a reservation from expected_state to new_state.

        Pre:  reservation_id identifies a row (otherwise returns False).
        Post: returns True iff the row was in expected_state AND (when
              enforce_no_overlap) no other CONFIRMED reservation overlaps it
              on the same resource; the change is then committed.
              Returns False otherwise and changes nothing.
        """
        sql = _TRANSITION_SQL + (_NO_OVERLAP_GUARD if enforce_no_overlap else "")
        result = self.db.execute(
            text(sql),
            {
                "id": reservation_id,
                "expected_state": expected_state,
                "new_state": new_state,
            },
        )
        applied = result.rowcount == 1
        self.db.commit()
        return applied
