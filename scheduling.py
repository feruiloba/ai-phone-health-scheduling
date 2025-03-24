from datetime import datetime, timedelta

class Patient:
    def __init__(self, patient_id, name=None, address=None, dob=None, payer_name=None, payer_id=None, has_referral=None, medical_complaint=None, phone=None, email=None):
        self.patient_id = patient_id
        self.name = name
        self.address=address
        self.dob=dob
        self.payer_name=payer_name
        self.payer_id=payer_id
        self.has_referral=has_referral
        self.medical_complaint=medical_complaint
        self.phone=phone
        self.email=email
    
    def __repr__(self):
        return f"Patient({self.patient_id}, {self.name})"

class Physician:
    def __init__(self, physician_id, name):
        self.physician_id = physician_id
        self.name = name
    
    def __repr__(self):
        return f"Physician({self.physician_id}, {self.name})"

class TimeSlot:
    def __init__(self, start_time, duration=30):
        self.start_time = start_time
        self.end_time = start_time + timedelta(minutes=duration)
    
    def __repr__(self):
        return f"Start: {self.start_time} - End: {self.end_time}, "

class Appointment:
    def __init__(self, patient, physician, time_slot):
        self.patient = patient
        self.physician = physician
        self.time_slot = time_slot
    
    def __repr__(self):
        return f"Appointment({self.patient}, {self.physician}, {self.time_slot})"

class Scheduler:
    def __init__(self):
        self.appointments = {}  # Dictionary where key is physician_id, value is list of timeslots
    
    def is_available(self, physician, time_slot):
        if physician.physician_id in self.appointments:
            # If any of the existing appointments overlap with the new appointment, then the timeslot is not available
            for ts in self.appointments[physician.physician_id]:
                if ts.start_time < time_slot.end_time and ts.end_time > time_slot.start_time:
                    return False
        return True
    
    def schedule_appointment(self, patient, physician, time_slot):
        if self.is_available(physician, time_slot):
            if physician.physician_id not in self.appointments:
                self.appointments[physician.physician_id] = []
            self.appointments[physician.physician_id].append(time_slot)
            return Appointment(patient, physician, time_slot)
        else:
            raise ValueError("Time slot not available")
        
    def get_available_time_slots(self, physician, date, start_hour=8, end_hour=17, duration=30):
        available_slots = []
        current_time = datetime(date.year, date.month, date.day, start_hour, 0)
        end_time = datetime(date.year, date.month, date.day, end_hour, 0)
        
        while current_time + timedelta(minutes=duration) <= end_time:
            time_slot = TimeSlot(current_time, duration)
            if self.is_available(physician, time_slot):
                available_slots.append(time_slot)
            current_time += timedelta(minutes=duration)
        
        return available_slots

    def __repr__(self):
        return f"Scheduler({self.appointments})"
