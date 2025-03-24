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
    async def set_patient_info(self,
            name: Annotated[str, llm.TypeInfo(description="The patient's name")],
            dob: Annotated[str, llm.TypeInfo(description="The patient's date of birth")],
            payer_name: Annotated[str, llm.TypeInfo(description="The patient's insurance payer name")],
            payer_id: Annotated[str, llm.TypeInfo(description="The patient's insurance payer id")],
            address: Annotated[str, llm.TypeInfo(description="The patient's address")],
            phone: Annotated[str, llm.TypeInfo(description="The patient's phone number")],
            email: Annotated[str, llm.TypeInfo(description="The patient's email")],
            medical_complaint: Annotated[str, llm.TypeInfo(description="The patient's chief medical complaint or reason that they're coming in")]):
        """Called when the patient provides their information."""
        
        self.patient.name = name
        self.patient.dob = dob
        self.patient.phone = phone
        self.patient.email = email
        self.patient.address = address
        self.patient.payer_name = payer_name
        self.patient.payer_id = payer_id
        self.patient.medical_complaint = medical_complaint
        self.logger.info("Patient information successfully recorded")

    @llm.ai_callable()
    async def set_physician_info(self,
            has_referral: Annotated[bool, llm.TypeInfo(description="Whether the patient has a referral")],
            physician_name: Annotated[str, llm.TypeInfo(description="The physician that the patient wants to see")]):
        """Called when the patient provides physician information. It returns a warning if the physician is not in the system and a message if the physician was succesfully recorded."""
        
        physician = get_physician(physician_name)
        
        if (physician == None):
            message = f"Incorrect physician name provided. Physician with name {physician_name} is not in the system."
            logger.info(message)
            return message
        
        self.physician = physician
        self.physician.is_referral = has_referral
        message = "Physician information was succesfully recorded."
        logger.info(message)
        return message

    @llm.ai_callable()
    async def set_date_time_info(
        self,
        day: Annotated[int, llm.TypeInfo(description="The desired day for the appointment")],
        month: Annotated[int, llm.TypeInfo(description="The desired month for the appointment")],
        hour: Annotated[int, llm.TypeInfo(description="The desired hour for the appointment")],
        minute: Annotated[int, llm.TypeInfo(description="The desired minute for the appointment")]):
        """Called when the patient has decided on a date and time. Returns a warning if no physician has been chosen or if the date and time are not available. Returns a success message if date is successfully recorded."""
        
        if (self.physician == None):
            message = f"Physician name has not been provided. Available physicians are: {get_physician_names()}"
            logger.info(message)
            return message
        
        appointment_date_time = datetime(datetime.now().year, month, day, hour, minute)
        timeslot = TimeSlot(appointment_date_time)

        if (not scheduler.is_available(self.physician, timeslot)):
            appointment_date = datetime(datetime.now().year, month, day)
            available_timeslots = ", ".join(scheduler.get_available_time_slots(self.physician, appointment_date))
            message = f"Time slot for day {day}, month {month}, hour {hour}, minute {minute} is not available for physician {self.physician.name}. Time slots available are: {available_timeslots}"
            logger.info(message)
            return message
        
        self.timeslot = timeslot
        message = "Time slot information was successfully recorded."
        logger.info(message)
        return message

    @llm.ai_callable()
    async def create_appointment(self):
        """Called after the patient has confirmed they want to make an appointment. Returns a warning if any information is missing and a successful message if the appointment was recorded."""

        if (self.patient.name == None):
            message = "Missing patient name. Cannot schedule appointment"
            self.logger.info(message)
            return message
        
        if (self.patient.dob == None):
            message = "Missing patient date of birth. Cannot schedule appointment"
            self.logger.info(message)
            return message

        if (self.patient.address == None):
            message = "Missing patient address. Cannot schedule appointment"
            self.logger.info(message)
            return message

        if (self.patient.phone == None):
            message = "Missing patient phone. Cannot schedule appointment"
            self.logger.info(message)
            return message

        if (self.patient.payer_name == None):
            message = "Missing patient payer name. Cannot schedule appointment"
            self.logger.info(message)
            return message
        
        if (self.patient.payer_id == None):
            message = "Missing patient payer ID. Cannot schedule appointment"
            self.logger.info(message)
            return message

        if (self.physician == None):
            message = "Physician name has not been provided. Cannot schedule appointment"
            self.logger.info(message)
            return message
        
        if (self.timeslot == None):
            message = "Missing date and time information. Cannot schedule appointment"
            self.logger.info(message)
            return message
        
        if (scheduler.is_available(self.physician, self.timeslot)):
            appointment_date = datetime(datetime.now().year, self.timeslot.start_time.month, self.timeslot.start_time.day)
            available_timeslots = ", ".join(scheduler.get_available_time_slots(self.physician, appointment_date))
            message = f"Time slot for day {self.timeslot.start_time.day}, month {self.timeslot.start_time.month}, hour {self.timeslot.start_time.hour}, minute {self.timeslot.start_time.minute} is not available for physician {self.physician.name}. Time slots available are: {available_timeslots}"
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
            "You need to collect information about the patient."
            "Collect patient's name."
            "Collect patient's date of birth."
            "Collect patient's insurance payer name."
            "Collect patient's insurance payer ID. Assume the patient is providing a number."
            "Collect patient's chief medical complaint or reason they are coming in."
            "Collect patient's address."
            "Collect patient's phone number and optionally email."
            "You need to collect information about the physician that the patient wants to see. The physician must be in the system."
            "Ask the patient if they have a referral. If they do, collect the name of the physician for which they had a referral."
            "If the patient doesn't have a referral, collect patient's preferred physician."
            "Collect patient's preferred date and time for scheduling an appointment."
            "Ensure that their preferred date and time is available."
            "Before creating the appointment, confirm all the information they provided."
            "After the appointment is scheduled, end the call."
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
