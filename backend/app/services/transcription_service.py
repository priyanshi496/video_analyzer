"""
Transcription Service using Whisper

Handles audio transcription with word-level timestamps using faster-whisper
for optimal performance on MacBook Air M-series (16GB RAM).
"""

import logging
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from faster_whisper import WhisperModel
except ImportError:
    # Fallback to regular whisper if faster-whisper not available
    try:
        import whisper as WhisperModel
        USING_FASTER_WHISPER = False
    except ImportError:
        WhisperModel = None
        USING_FASTER_WHISPER = False
else:
    USING_FASTER_WHISPER = True

from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

class TranscriptionService:
    """Handles audio transcription with word-level timestamps"""
    
    def __init__(self):
        self.model = None
        self.model_size = "small"  # Optimal for 16GB RAM MacBook Air
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize Whisper model on first use"""
        if WhisperModel is None:
            raise ImportError(
                "Whisper not installed. Run: pip install faster-whisper "
                "or pip install openai-whisper"
            )
        
        try:
            if USING_FASTER_WHISPER:
                # faster-whisper (recommended)
                self.model = WhisperModel(
                    self.model_size,
                    device="auto",  # Will use Apple Silicon GPU if available
                    compute_type="int8"  # Optimize for memory usage
                )
                logger.info(f"Initialized faster-whisper model: {self.model_size}")
            else:
                # Standard whisper fallback
                self.model = WhisperModel.load_model(self.model_size)
                logger.info(f"Initialized whisper model: {self.model_size}")
                
        except Exception as e:
            logger.error(f"Failed to initialize Whisper model: {str(e)}")
            raise

    async def transcribe_with_timestamps(
        self, 
        audio_path: str, 
        job_id: str
    ) -> Dict[str, Any]:
        """
        Transcribe audio with word-level timestamps
        
        Args:
            audio_path: Path to audio file
            job_id: Job ID for storage and logging
            
        Returns:
            Dict containing full transcript and word-level data
        """
        logger.info(f"Starting transcription for job {job_id}")
        
        try:
            # Run transcription in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                self._transcribe_sync, 
                audio_path
            )
            
            # Save transcript to storage
            await self._save_transcript(job_id, result)
            
            logger.info(f"Transcription completed for job {job_id}")
            return result
            
        except Exception as e:
            logger.error(f"Transcription failed for job {job_id}: {str(e)}")
            raise

    def _transcribe_sync(self, audio_path: str) -> Dict[str, Any]:
        """Synchronous transcription (runs in thread pool)"""
        
        if USING_FASTER_WHISPER:
            return self._transcribe_faster_whisper(audio_path)
        else:
            return self._transcribe_standard_whisper(audio_path)

    def _transcribe_faster_whisper(self, audio_path: str) -> Dict[str, Any]:
        """Transcribe using faster-whisper with word timestamps"""
        segments, info = self.model.transcribe(
            audio_path,
            word_timestamps=True,
            language="en",  # Can be auto-detected or specified
            vad_filter=True,  # Voice Activity Detection
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        # Convert to standard format
        words = []
        full_text = ""
        
        for segment in segments:
            segment_text = segment.text.strip()
            full_text += segment_text + " "
            
            # Extract word-level timestamps
            if hasattr(segment, 'words') and segment.words:
                for word in segment.words:
                    words.append({
                        "word": word.word.strip(),
                        "start": word.start,
                        "end": word.end,
                        "confidence": getattr(word, 'probability', 1.0)
                    })
        
        return {
            "text": full_text.strip(),
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "words": words,
            "segments": [
                {
                    "start": seg.start,
                    "end": seg.end, 
                    "text": seg.text,
                    "words": [
                        {
                            "word": w.word.strip(),
                            "start": w.start,
                            "end": w.end,
                            "confidence": getattr(w, 'probability', 1.0)
                        } for w in (seg.words or [])
                    ]
                } for seg in segments
            ]
        }

    def _transcribe_standard_whisper(self, audio_path: str) -> Dict[str, Any]:
        """Transcribe using standard whisper (fallback)"""
        result = self.model.transcribe(
            audio_path,
            word_timestamps=True,
            language="en"
        )
        
        # Extract word-level data from segments
        words = []
        for segment in result.get("segments", []):
            segment_words = segment.get("words", [])
            for word_data in segment_words:
                words.append({
                    "word": word_data["word"].strip(),
                    "start": word_data["start"],
                    "end": word_data["end"],
                    "confidence": word_data.get("confidence", 1.0)
                })
        
        return {
            "text": result["text"],
            "language": result["language"],
            "language_probability": 1.0,
            "duration": result.get("duration", 0),
            "words": words,
            "segments": result.get("segments", [])
        }

    async def _save_transcript(self, job_id: str, transcript_data: Dict) -> str:
        """Save transcript to storage using upload_json"""
        storage_key = f"transcripts/{job_id}/transcript.json"
        storage_service.upload_json(transcript_data, storage_key)

        summary = {
            "job_id": job_id,
            "text": transcript_data["text"][:500] + "..." if len(transcript_data["text"]) > 500 else transcript_data["text"],
            "language": transcript_data["language"],
            "duration": transcript_data["duration"],
            "word_count": len(transcript_data["words"]),
        }
        storage_service.upload_json(summary, f"transcripts/{job_id}/summary.json")

        return storage_service.generate_presigned_url(storage_key)

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages"""
        # Common languages supported by Whisper
        return [
            "en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "zh", 
            "hi", "ar", "bn", "ur", "ta", "te", "ml", "kn", "gu", "pa"
        ]

    def estimate_processing_time(self, duration_seconds: float) -> float:
        """Estimate processing time based on audio duration"""
        # faster-whisper on MacBook Air M-series (small model)
        # Roughly 8-12 seconds for 1 minute of audio
        if USING_FASTER_WHISPER:
            return duration_seconds * 0.15  # ~15% of audio duration
        else:
            return duration_seconds * 0.25  # ~25% of audio duration