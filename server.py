import os
import time
import base64
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

# Import project services
from services.persistence.db import (
    init_db,
    get_or_create_user,
    add_exercise,
    get_users_exercises
)
from services.coaching.llm import LLMCoach
from services.coaching.tts import TextToSpeech
from services.coaching.voice_pipeline import VoicePipeline

# Import detectors
from detectors.squat import SquatDetector
from detectors.pushup import PushUpDetector
from detectors.biceps_curl import BicepsCurlDetector
from detectors.shoulder_press import ShoulderPressDetector
from detectors.lunges import LungesDetector

from groq import Groq

# Initialize database (only if DATABASE_URL is provided)
try:
    init_db()
except Exception as e:
    print(f"Warning: could not initialize DB at startup: {e}")

app = FastAPI(title="Apna AI Gym Coach API")

# Enable CORS for frontend connection.
# Default to the deployed Vercel frontend plus local dev origins.
default_allow_origins = {
    "https://ai-gym-coach-frontend-six.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

allow_origins_env = os.environ.get("ALLOW_ORIGINS", "")
allow_origins = set(default_allow_origins)

if allow_origins_env.strip() == "*":
    allow_origins = {"*"}
elif allow_origins_env.strip():
    allow_origins.update(
        origin.strip()
        for origin in allow_origins_env.split(",")
        if origin.strip()
    )

allow_origins = sorted(allow_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store
# Maps user_id (int) -> session state dictionary
ACTIVE_SESSIONS: Dict[int, Dict[str, Any]] = {}

DETECTOR_CLASSES = {
    "Squats": SquatDetector,
    "Push-ups": PushUpDetector,
    "Biceps Curls (Dumbbell)": BicepsCurlDetector,
    "Shoulder Press": ShoulderPressDetector,
    "Lunges": LungesDetector,
}

# Pydantic Schemas
class LoginRequest(BaseModel):
    username: str

class WorkoutStartRequest(BaseModel):
    user_id: int
    exercise_type: str
    target_sets: int
    reps_per_set: int

class LandmarkInput(BaseModel):
    x: float
    y: float
    visibility: float

class WorkoutProcessRequest(BaseModel):
    user_id: int
    landmarks: List[LandmarkInput]

class LandmarkAdapter:
    def __init__(self, x, y, visibility):
        self.x = x
        self.y = y
        self.visibility = visibility

@app.post("/api/auth/login")
async def login(payload: LoginRequest):
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    try:
        user = get_or_create_user(username)
        return {
            "id": user["id"],
            "username": user["username"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database login error: {str(e)}")

@app.get("/api/history/{user_id}")
async def get_history(user_id: int):
    try:
        rows = get_users_exercises(user_id)
        formatted_history = [
            {
                "exercise_name": r["exercise_name"],
                "reps": r["reps"],
                "sets": r["sets"],
                "time": r["time"],
                "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
            }
            for r in rows
        ]
        return formatted_history
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database fetch history error: {str(e)}")

@app.post("/api/workout/start")
async def start_workout(payload: WorkoutStartRequest):
    user_id = payload.user_id
    exercise_type = payload.exercise_type
    target_sets = payload.target_sets
    reps_per_set = payload.reps_per_set

    if exercise_type not in DETECTOR_CLASSES:
        raise HTTPException(status_code=400, detail=f"Unsupported exercise type: {exercise_type}")

    # Initialize Groq client
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("Warning: GROQ_API_KEY not found in environment.")
    
    try:
        groq_client = Groq(api_key=api_key)
        llm_coach = LLMCoach(groq_client)
        tts = TextToSpeech()
        voice_pipeline = VoicePipeline(llm_coach, tts)
    except Exception as e:
        print(f"Error initializing voice pipeline: {e}")
        voice_pipeline = None

    # Instantiate detector
    detector = DETECTOR_CLASSES[exercise_type]()

    # Setup session
    session = {
        "exercise_type": exercise_type,
        "target_sets": target_sets,
        "reps_per_set": reps_per_set,
        "detector": detector,
        "voice_pipeline": voice_pipeline,
        "last_saved_sets_completed": 0,
        "last_notified_workout_complete": False,
        "set_cycle_started_at": time.time(),
    }

    ACTIVE_SESSIONS[user_id] = session

    # Trigger start greeting
    coach_feedback = "Session started. Let's get to work!"
    audio_base64 = None

    if voice_pipeline:
        try:
            res = voice_pipeline.process_event(
                event="workout_started",
                exercise=exercise_type,
                metrics={}
            )
            if res:
                voice_bytes, text = res
                coach_feedback = text
                if voice_bytes:
                    audio_base64 = base64.b64encode(voice_bytes).decode("utf-8")
        except Exception as e:
            print(f"Error in start workout voice: {e}")

    return {
        "status": "started",
        "exercise_type": exercise_type,
        "coach_feedback": coach_feedback,
        "audio": audio_base64
    }

@app.post("/api/workout/process")
async def process_workout(payload: WorkoutProcessRequest):
    user_id = payload.user_id
    landmarks_input = payload.landmarks

    if user_id not in ACTIVE_SESSIONS:
        raise HTTPException(status_code=404, detail="Active session not found. Please start a session first.")

    session = ACTIVE_SESSIONS[user_id]
    detector = session["detector"]
    voice_pipeline = session["voice_pipeline"]
    exercise_type = session["exercise_type"]
    reps_per_set = session["reps_per_set"]
    target_sets = session["target_sets"]

    coach_feedback = None
    audio_base64 = None
    event_triggered = None

    # Check if landmarks are present (pose detected)
    pose_detected = len(landmarks_input) > 0

    if not pose_detected:
        # Trigger no pose detected warnings
        if voice_pipeline:
            try:
                res = voice_pipeline.process_event(
                    event="no_pose_detected",
                    exercise=exercise_type,
                    metrics={"issue": "No pose detected! Please step into the camera frame."}
                )
                if res:
                    voice_bytes, text = res
                    coach_feedback = text
                    if voice_bytes:
                        audio_base64 = base64.b64encode(voice_bytes).decode("utf-8")
                    event_triggered = "no_pose_detected"
            except Exception as e:
                print(f"Error in no pose detected voice: {e}")

        return {
            "reps": detector.reps,
            "sets_completed": session["last_saved_sets_completed"],
            "current_set_reps": detector.reps % reps_per_set if reps_per_set > 0 else 0,
            "workout_completed": session["last_notified_workout_complete"],
            "pose_detected": False,
            "metrics": {
                "pose_detected": False,
                "reps": detector.reps
            },
            "coach_feedback": coach_feedback,
            "audio": audio_base64,
            "event_triggered": event_triggered
        }

    # Adapt pydantic landmarks to detector landmark classes (which expect attributes .x, .y, .visibility)
    adapted_landmarks = [
        LandmarkAdapter(lm.x, lm.y, lm.visibility)
        for lm in landmarks_input
    ]

    try:
        # Run detection logic
        metrics = detector.process(adapted_landmarks)
        metrics["pose_detected"] = True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running detector: {str(e)}")

    reps = metrics.get("reps", 0)
    if reps is None:
        reps = 0

    # Calculate set progress
    if reps_per_set > 0 and target_sets > 0:
        sets_completed = reps // reps_per_set
        current_set_reps = reps % reps_per_set
        workout_completed = sets_completed >= target_sets
    else:
        sets_completed = 0
        current_set_reps = 0
        workout_completed = False

    last_saved_sets = session["last_saved_sets_completed"]

    # Check set completion
    if target_sets > 0 and reps_per_set > 0 and sets_completed > last_saved_sets:
        newly_completed = sets_completed - last_saved_sets
        now_ts = time.time()
        started_at = session["set_cycle_started_at"]
        time_taken = now_ts - started_at

        # Save completed set to database
        try:
            add_exercise(user_id, exercise_type, newly_completed * reps_per_set, newly_completed, int(time_taken))
        except Exception as e:
            print(f"Error saving exercise to DB: {e}")

        # Trigger set completed audio
        if voice_pipeline:
            try:
                res = voice_pipeline.process_event(
                    event="set_completed",
                    exercise=exercise_type,
                    metrics=metrics
                )
                if res:
                    voice_bytes, text = res
                    coach_feedback = text
                    if voice_bytes:
                        audio_base64 = base64.b64encode(voice_bytes).decode("utf-8")
                    event_triggered = "set_completed"
            except Exception as e:
                print(f"Error in set completed voice: {e}")

        session["set_cycle_started_at"] = now_ts
        session["last_saved_sets_completed"] = sets_completed

    # Check workout completion
    elif workout_completed and not session["last_notified_workout_complete"]:
        session["last_notified_workout_complete"] = True
        if voice_pipeline:
            try:
                res = voice_pipeline.process_event(
                    event="workout_completed",
                    exercise=exercise_type,
                    metrics=metrics
                )
                if res:
                    voice_bytes, text = res
                    coach_feedback = text
                    if voice_bytes:
                        audio_base64 = base64.b64encode(voice_bytes).decode("utf-8")
                    event_triggered = "workout_completed"
            except Exception as e:
                print(f"Error in workout completed voice: {e}")

    # Fallback to ongoing form checks
    else:
        if voice_pipeline:
            try:
                res = voice_pipeline.process_event(
                    event="ongoing_form_check",
                    exercise=exercise_type,
                    metrics=metrics
                )
                if res:
                    voice_bytes, text = res
                    coach_feedback = text
                    if voice_bytes:
                        audio_base64 = base64.b64encode(voice_bytes).decode("utf-8")
                    event_triggered = "ongoing_form_check"
            except Exception as e:
                print(f"Error in ongoing form check voice: {e}")

    return {
        "reps": reps,
        "sets_completed": sets_completed,
        "current_set_reps": current_set_reps,
        "workout_completed": workout_completed,
        "pose_detected": True,
        "metrics": metrics,
        "coach_feedback": coach_feedback,
        "audio": audio_base64,
        "event_triggered": event_triggered
    }

@app.post("/api/workout/end")
async def end_workout(payload: Dict[str, int]):
    user_id = payload.get("user_id")
    if not user_id or user_id not in ACTIVE_SESSIONS:
        return {"status": "no_active_session"}

    session = ACTIVE_SESSIONS.pop(user_id)
    detector = session["detector"]
    voice_pipeline = session["voice_pipeline"]
    exercise_type = session["exercise_type"]
    metrics = {
        "reps": detector.reps,
        "pose_detected": False
    }

    coach_feedback = None
    audio_base64 = None

    if voice_pipeline and not session["last_notified_workout_complete"]:
        try:
            res = voice_pipeline.process_event(
                event="workout_completed",
                exercise=exercise_type,
                metrics=metrics
            )
            if res:
                voice_bytes, text = res
                coach_feedback = text
                if voice_bytes:
                    audio_base64 = base64.b64encode(voice_bytes).decode("utf-8")
        except Exception as e:
            print(f"Error in end session voice: {e}")

    return {
        "status": "ended",
        "coach_feedback": coach_feedback,
        "audio": audio_base64
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
