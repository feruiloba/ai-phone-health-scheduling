import unittest
from datetime import datetime
from scheduling import (Scheduler, Patient, TimeSlot, Physician)


class TestScheduler(unittest.TestCase):
    def setUp(self):
        """Set up a test environment with a Scheduler, Physician, and Patient."""
        self.scheduler = Scheduler()
        self.physician = Physician(101, "Dr. Smith")
        self.patient = Patient(1, "John Doe", dob=datetime(1995, 10, 7), phone="123-456-7890")
        self.date = datetime(2025, 3, 25)

    def test_schedule_appointment_success(self):
        """Test scheduling an available appointment."""
        time_slot = TimeSlot(datetime(2025, 3, 25, 10, 0))
        appointment = self.scheduler.schedule_appointment(self.patient, self.physician, time_slot)
        self.assertIn(self.physician.physician_id, self.scheduler.appointments)
        self.assertIn(time_slot, self.scheduler.appointments[self.physician.physician_id])
        self.assertEqual(appointment.patient, self.patient)
        self.assertEqual(appointment.physician, self.physician)
        self.assertEqual(appointment.time_slot, time_slot)

    def test_schedule_appointment_conflict(self):
        """Test scheduling an overlapping appointment should fail."""
        time_slot1 = TimeSlot(datetime(2025, 3, 25, 10, 0))
        time_slot2 = TimeSlot(datetime(2025, 3, 25, 10, 15))  # Overlaps with first slot
        self.scheduler.schedule_appointment(self.patient, self.physician, time_slot1)
        with self.assertRaises(ValueError):
            self.scheduler.schedule_appointment(self.patient, self.physician, time_slot2)

    def test_get_available_time_slots(self):
        """Test getting available time slots before and after scheduling."""
        # Get all available slots before scheduling
        available_slots_before = self.scheduler.get_available_time_slots(self.physician, self.date)
        self.assertTrue(len(available_slots_before) > 0)  # Should have slots

        # Schedule an appointment at 10:00 AM
        time_slot = TimeSlot(datetime(2025, 3, 25, 10, 0))
        self.scheduler.schedule_appointment(self.patient, self.physician, time_slot)

        # Get available slots after scheduling
        available_slots_after = self.scheduler.get_available_time_slots(self.physician, self.date)
        self.assertNotIn(time_slot, available_slots_after)  # 10:00 AM slot should be gone

if __name__ == '__main__':
    unittest.main()
