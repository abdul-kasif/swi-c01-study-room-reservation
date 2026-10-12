from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from src.domain import ReservationEntity

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


Base.metadata.create_all(bind=engine)


class ReservationRepository:
    def __init__(self, db: Session):
        self.db = db

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
        model = (
            self.db.query(ReservationModel)
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
        """Check whether a confirmed reservation overlaps the requested interval."""
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
