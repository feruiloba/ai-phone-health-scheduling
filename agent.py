from datetime import datetime, date
import logging
from typing import Annotated
from difflib import SequenceMatcher
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
    metrics,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import (
    elevenlabs,
    openai,
    deepgram,
    noise_cancellation,
    silero,
    turn_detector,
)
from livekit import api, rtc

from mailer import Mailer
from scheduling import ( Scheduler, Patient, Physician, TimeSlot )

scheduler = Scheduler()
physicians = [
    Physician(1, "Dr. Smith"),
    Physician(2, "Dr. Jones"),
    Physician(3, "Dr. Allendorf"),
    Physician(4, "Dr. Paul"),
    Physician(5, "Dr. Sanchez")
]
timeslots = [
    TimeSlot(datetime(2025, 3, 25, 10, 0)),
    TimeSlot(datetime(2025, 3, 25, 11, 0)),
    TimeSlot(datetime(2025, 3, 25, 12, 0)),
    TimeSlot(datetime(2025, 3, 25, 13, 0)),
    TimeSlot(datetime(2025, 3, 25, 14, 0)),
    TimeSlot(datetime(2025, 3, 25, 15, 0)),
]

mailer = Mailer()

load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")

def get_physician_names():
    physician_names = []
    for physician in physicians:
        physician_names.append(physician.name)

    return physician_names

def get_physician(physician_name):
    # the threshold of similarity between what the AI hears and what the actual doctor name is can be tweaked
    return next(filter(lambda physician: SequenceMatcher(None, physician.name, physician_name).ratio() > 0.5 , physicians), None)

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


class AssistantFnc(llm.FunctionContext):
    """
    The class defines a set of LLM functions that the assistant can execute.
    """

    def __init__(self, *, api: api.LiveKitAPI, participant: rtc.RemoteParticipant, room: rtc.Room, logger: logging.Logger):
        super().__init__()
        self.api = api
        self.participant = participant
        self.room = room
        self.patient = Patient(patient_id=participant.sid)
        self.physician = None
        self.timeslot = None
        self.logger = logger

    @llm.ai_callable()
    async def set_name(self, name: Annotated[str, llm.TypeInfo(description="The patient's name")]):
        """Called when the patient provides their name."""
        self.patient.name = name

    @llm.ai_callable()
    async def set_dob(self, dob: Annotated[str, llm.TypeInfo(description="The patient's date of birth")]):
        """Called when the patient provides their date of birth."""
        self.patient.dob = dob

    @llm.ai_callable()
    async def set_payer_name(self, payer_name: Annotated[str, llm.TypeInfo(description="The patient's insurance payer name")]):
        """Called when the patient provides their insurance payer name."""
        self.patient.payer_name = payer_name

    @llm.ai_callable()
    async def set_payer_id(self, payer_id: Annotated[str, llm.TypeInfo(description="The patient's insurance payer id")]):
        """Called when the patient provides their insurance payer id."""
        self.patient.payer_id = payer_id

    @llm.ai_callable()
    async def set_referral(self, has_referral: Annotated[bool, llm.TypeInfo(description="Whether the patient has a referral")]):
        """Called when the patient says whether they have a referral."""
        self.patient.has_referral = has_referral

    @llm.ai_callable()
    async def set_physician(self, physician_name: Annotated[str, llm.TypeInfo(description="The physician that the patient wants to see")]):
        """Called when the patient provides a physician name. It returns a warning if the physician is not in the system and a message if the physician was succesfully recorded."""
        physician = get_physician(physician_name)
        
        if (physician != None):
            self.physician = physician
            message = "Physician was succesfully recorded."
            logger.info(message)
            return message
        else:
            message = f"Incorrect physician name provided. Physician with name {physician_name} is not in the system."
            logger.info(message)
            return message
    
    @llm.ai_callable()
    async def set_chief_medical_complaint(self, medical_complaint: Annotated[str, llm.TypeInfo(description="The patient's chief medical complaint or reason that they're coming in")]):
        """Called when the patient provides their chief medical complaint or reason that they're coming in."""
        self.patient.medical_complaint = medical_complaint

    @llm.ai_callable()
    async def set_address(self, address: Annotated[str, llm.TypeInfo(description="The patient's address")]):
        """Called when the patient provides their address"""
        self.patient.address = address

    @llm.ai_callable()
    async def set_phone_email(self, phone: Annotated[str, llm.TypeInfo(description="The patient's phone number")], email: Annotated[str, llm.TypeInfo(description="The patient's email")]):
        """Called when the patient provides their phone number, and optionally, their email"""
        self.patient.phone = phone
        self.patient.email = email

    @llm.ai_callable()
    async def get_physicians(self):
        """Called when the patient asks for the available physicians. It returns a list of physicians to choose from."""
        
        return get_physician_names()

    @llm.ai_callable()
    async def get_physician_timeslots(self, day: Annotated[int, llm.TypeInfo(description="The desired day for the appointment")], month: Annotated[int, llm.TypeInfo(description="The desired month for the appointment")]):
        """Used for getting all the available dates and times for a given physician. Returns a list of all the available time slots in the format "Start: yyyy-mm-dd hh:mm:ss - End: yyyy-mm-dd hh:mm:ss" separated by commas. It also returns a warning if the patient has not provided a preferred physician."""

        if (self.physician == None):
            message = "Physician name has not been provided"
            logger.info(message)
            return message
        else:
            appointment_date = datetime(datetime.now().year, month, day)
            available_timeslots = ", ".join(scheduler.get_available_time_slots(self.physician, appointment_date))
            logger.info("Providing available timeslots", available_timeslots)
            return available_timeslots
    

    async def check_physician_availability(
            self,
            day: Annotated[int, llm.TypeInfo(description="The desired day for the appointment")],
            month: Annotated[int, llm.TypeInfo(description="The desired month for the appointment")],
            hour: Annotated[int, llm.TypeInfo(description="The desired hour for the appointment")],
            minute: Annotated[int, llm.TypeInfo(description="The desired minute for the appointment")]):
        """Used to check if a given date and time are available for a given physician. Returns a message confirming or rejecting the given date and times or a warning if the patient has not provided a preferred physician"""

        if (self.physician == None):
            message = "Physician name has not been provided"
            logger.info(message)
            return message
        
        appointment_date = datetime(datetime.now().year, month, day)
        timeslot = TimeSlot(appointment_date)

        if (scheduler.is_available(self.physician, timeslot)):
            message = f"Time slot for day {day}, month {month}, hour {hour}, minute {minute} is available for physician {self.physician.name}"
            logger.info(message)
        else:
            message = f"Time slot for day {day}, month {month}, hour {hour}, minute {minute} is not available for physician {self.physician.name}"
            logger.info(message)

        return message

    async def set_timeslot(
            self,
            day: Annotated[int, llm.TypeInfo(description="The desired day for the appointment")],
            month: Annotated[int, llm.TypeInfo(description="The desired month for the appointment")],
            hour: Annotated[int, llm.TypeInfo(description="The desired hour for the appointment")],
            minute: Annotated[int, llm.TypeInfo(description="The desired minute for the appointment")]):
        """Used for collecting the patient's preferred date and time for an appointment. Returns a success message if the date and time recorded correctly and warnings if the physician name has not been provided or if the date and time provided are unavailable."""
        
        if (self.physician == None):
            message = "Physician name has not been provided"
            logger.info(message)
            return message
        
        appointment_date = datetime(datetime.now().year, month, day, hour, minute)
        timeslot = TimeSlot(appointment_date)

        if (scheduler.is_available(self.physician, timeslot)):
            self.timeslot = timeslot
            message = "Time slot was recorded correctly."
            logger.info(message)
            return message
        else:
            message = f"Time slot for day {day}, month {month}, hour {hour}, minute {minute} is not available for physician {self.physician.name}"
            logger.info(message)
            return message
    
    @llm.ai_callable()
    async def get_appointment_confirmation(self):
        """Used to confirm the desired physician, date and time for the appointment. Returns a warning if any information is missing or a success message if everything looks good."""

        if (self.physician == None):
            message = "Physician name has not been provided"
            logger.info(message)
            return message
        
        if (self.timeslot == None):
            message = "Missing date and time data"
            logger.info(message)
            return message

        return "Everything lookgs good. Physician and time slot data have been recorded."

    @llm.ai_callable()
    async def create_appointment(self):
        """Called after the patient has confirmed that he wants to make an appointment. Returns a warning if any information is missing and a successful message if the appointment was recorded."""

        if (self.physician == None):
            message = "Physician name has not been provided. Cannot schedule appointment"
            self.logger.info(message)
            return message
        
        if (self.timeslot == None):
            message = "Missing date and time information. Cannot schedule appointment"
            self.logger.info(message)
            return message
        
        if (scheduler.is_available(self.physician, self.timeslot)):
            message = f"The time slot provided for {self.timeslot.start_time} is not available for physician {self.physician.name}"
            self.logger.info(message)
            return message

        scheduler.schedule_appointment(self.patient, self.physician, self.timeslot)
        message = "The appointment was successfully recorded!"
        mailer.send_email(message, f"Appointment confirmed. \n Physician: {self.physician.name} \n Patient: {self.patient.name} \n Time slot: {self.timeslot}")
        self.logger.info(message)
        return message
        
    @llm.ai_callable()
    async def end_call(self):
        """Used for ending the call. Should only be called if the user wants to end the call or an appointment has been scheduled."""
        logger.info(f"ending the call for {self.participant.identity}")
        try:
            await self.api.room.remove_participant(
                api.RoomParticipantIdentity(
                    room=self.room.name,
                    identity=self.participant.identity,
                )
            )
        except Exception as e:
            # it's possible that the user has already hung up, this error can be ignored
            self.logger.info(f"received error while ending call: {e}")

async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=(
            "You are a voice assistant created by Assort Health. Your interface with users will be voice."
            "You should use short and concise responses, and avoiding usage of unpronouncable punctuation."
            "You work in a hospital. Your job is to answer calls from patients who want to schedule an appointment."
            "You need to collect information from patients. It is essential to collect the entirety of the data for each patient."
            "Collect patient's name."
            "Collect patient's date of birth."
            "Collect patient's insurance payer name."
            "Collect patient's insurance payer ID. Assume the patient is providing a number."
            "Collect patient's chief medical complaint or reason they are coming in."
            "Collect patient's address."
            "Collect patient's phone number and optionally email."
            "Ask patient if they have a referral. If they do, collect the name of the physician for which they had a referral."
            "If the patient doesn't have a referral, collect patient's preferred physician."
            "If the patient is struggling to choose a physician, provide the list of available physicians"
            "Collect patient's preferred date and time for scheduling an appointment."
            "If a patient is struggling to choose a preferred date and time, provide a list of time slots available for the physician they chose."
            "After the appointment is scheduled, end the call"
        ),
    )

    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"connected to room {ctx.room.name}. Starting voice assistant for participant {participant.identity}")

    eleven_tts=elevenlabs.tts.TTS(
        model="eleven_turbo_v2_5",
        voice=elevenlabs.tts.Voice(
            id="pFZP5JQG7iQjIQuC4Bku",
            name="Lily",
            category="premade",
            settings=elevenlabs.tts.VoiceSettings(
                stability=0.71,
                similarity_boost=0.5,
                style=0.0,
                use_speaker_boost=True
            ),
        ),
        language="en",
        streaming_latency=3,
        enable_ssml_parsing=False,
        chunk_length_schedule=[80, 120, 200, 260],
    )

    deepgram_stt = deepgram.stt.STT(
        model="nova-2-general",
        interim_results=True,
        smart_format=True,
        punctuate=True,
        filler_words=True,
        profanity_filter=False,
        keywords=[("LiveKit", 1.5)],
        language="en-US",
    )

    fnc_ctx = AssistantFnc(api=ctx.api, participant=participant, room=ctx.room, logger=logger)

    # This project is configured to use Deepgram STT, OpenAI LLM and Eleven TTS plugins
    # Other great physicians exist like Cerebras, ElevenLabs, Groq, Play.ht, Rime, and more
    # Learn more and pick the best one for your app:
    # https://docs.livekit.io/agents/plugins
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram_stt,
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=eleven_tts,
        fnc_ctx=fnc_ctx,
        # use LiveKit's transformer-based turn detector
        turn_detector=turn_detector.EOUModel(),
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.5,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=2.0,
        max_nested_fnc_calls=5,
        # enable background voice & noise cancellation, powered by Krisp
        # included at no additional cost with LiveKit Cloud
        noise_cancellation=noise_cancellation.BVC(),
        chat_ctx=initial_ctx,
    )

    usage_collector = metrics.UsageCollector()
    @agent.on("metrics_collected")
    def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
        metrics.log_metrics(agent_metrics)
        usage_collector.collect(agent_metrics)

    agent.start(ctx.room, participant)

    # The agent should be polite and greet the user when it joins :)
    await agent.say("Hey, how can I help you today? Please keep in mind that I may take some time between responses due to latency.", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="inbound-agent",
            # the type of worker to create, either JT_ROOM or JT_PUBLISHER
            worker_type=WorkerType.ROOM,
        ),
    )
