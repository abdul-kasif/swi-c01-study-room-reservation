class NotificationGateway:
    @staticmethod
    def notify(user_id: str, message: str) -> None:
        print(f"[NotificationService] To {user_id}: {message}")

    @classmethod
    def notify_state_change(
        cls,
        user_id: str,
        reservation_id: int,
        new_state: str,
        admin_id: str | None = None,
    ) -> None:
        if new_state == "PENDING_APPROVAL":
            msg = f"Reservation {reservation_id} is pending administrator approval."
        elif new_state == "CONFIRMED" and admin_id:
            msg = f"Reservation {reservation_id} was approved by Administrator {admin_id}."
        elif new_state == "CONFIRMED":
            msg = f"Reservation {reservation_id} confirmed."
        elif new_state == "CANCELLED" and admin_id:
            msg = f"Reservation {reservation_id} was rejected by Administrator {admin_id}."
        else:
            msg = f"Reservation {reservation_id} has been cancelled."
        cls.notify(user_id, msg)
