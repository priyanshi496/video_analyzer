#!/usr/bin/env python3
"""
Test script to verify podcast processing setup

Run this to check if all dependencies are properly installed
and the services can be initialized.
"""

import sys
import os
import asyncio
import tempfile
import logging

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_imports():
    """Test if all required imports work"""
    print("🔍 Testing imports...")
    
    try:
        # Test Whisper
        try:
            from faster_whisper import WhisperModel
            print("✅ faster-whisper imported successfully")
        except ImportError:
            print("⚠️  faster-whisper not available, trying standard whisper...")
            import whisper
            print("✅ openai-whisper imported successfully")
    except ImportError as e:
        print(f"❌ Whisper import failed: {e}")
        return False
    
    # Test other dependencies
    try:
        import asyncio
        import nest_asyncio
        print("✅ asyncio and nest-asyncio imported")
    except ImportError as e:
        print(f"❌ Asyncio import failed: {e}")
        return False
    
    # Test service imports
    try:
        from app.services.podcast_service import PodcastService, PodcastProcessingOptions
        from app.services.transcription_service import TranscriptionService
        from app.services.caption_service import CaptionService
        from app.services.moment_detection_service import MomentDetectionService
        from app.services.zoom_effects_service import ZoomEffectsService
        print("✅ All podcast services imported successfully")
    except ImportError as e:
        print(f"❌ Service import failed: {e}")
        return False
    
    return True

def test_whisper_initialization():
    """Test Whisper model initialization"""
    print("\n🎙️ Testing Whisper model initialization...")
    
    try:
        from app.services.transcription_service import TranscriptionService
        service = TranscriptionService()
        print("✅ TranscriptionService initialized successfully")
        
        # Test model loading
        if service.model is not None:
            print(f"✅ Whisper model loaded: {service.model_size}")
        else:
            print("⚠️  Whisper model not loaded (will load on first use)")
            
        return True
    except Exception as e:
        print(f"❌ Whisper initialization failed: {e}")
        return False

def test_services_initialization():
    """Test all service initializations"""
    print("\n🔧 Testing service initialization...")
    
    try:
        from app.services.podcast_service import PodcastService
        from app.services.caption_service import CaptionService
        from app.services.moment_detection_service import MomentDetectionService
        from app.services.zoom_effects_service import ZoomEffectsService
        
        # Initialize services
        podcast_service = PodcastService()
        caption_service = CaptionService()
        moment_service = MomentDetectionService()
        zoom_service = ZoomEffectsService()
        
        print("✅ All services initialized successfully")
        return True
    except Exception as e:
        print(f"❌ Service initialization failed: {e}")
        return False

def test_ffmpeg_availability():
    """Test FFmpeg and required filters"""
    print("\n🎬 Testing FFmpeg availability...")
    
    import subprocess
    
    try:
        # Test FFmpeg
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ FFmpeg is available")
        else:
            print("❌ FFmpeg not found")
            return False
            
        # Test specific filters
        result = subprocess.run(['ffmpeg', '-filters'], 
                              capture_output=True, text=True, timeout=10)
        filters_output = result.stdout
        
        required_filters = ['drawtext', 'zoompan']
        for filter_name in required_filters:
            if filter_name in filters_output:
                print(f"✅ FFmpeg filter '{filter_name}' available")
            else:
                print(f"❌ FFmpeg filter '{filter_name}' missing")
                return False
                
        return True
        
    except subprocess.TimeoutExpired:
        print("❌ FFmpeg test timed out")
        return False
    except FileNotFoundError:
        print("❌ FFmpeg not found in PATH")
        return False
    except Exception as e:
        print(f"❌ FFmpeg test failed: {e}")
        return False

def test_caption_generation():
    """Test caption generation with sample data"""
    print("\n📝 Testing caption generation...")
    
    try:
        from app.services.caption_service import CaptionService
        
        # Sample word data
        sample_words = [
            {"word": "This", "start": 0.0, "end": 0.3},
            {"word": "is", "start": 0.3, "end": 0.5},
            {"word": "a", "start": 0.5, "end": 0.7},
            {"word": "test", "start": 0.7, "end": 1.0},
            {"word": "of", "start": 1.0, "end": 1.2},
            {"word": "caption", "start": 1.2, "end": 1.6},
            {"word": "generation", "start": 1.6, "end": 2.2}
        ]
        
        caption_service = CaptionService()
        
        # Test async function
        async def test_async():
            segments = await caption_service.generate_line_captions(sample_words, words_per_line=3)
            return segments
        
        segments = asyncio.run(test_async())
        
        if segments and len(segments) > 0:
            print(f"✅ Generated {len(segments)} caption segments")
            for i, segment in enumerate(segments):
                print(f"   Segment {i+1}: '{segment['text']}' ({segment['start_time']:.1f}s - {segment['end_time']:.1f}s)")
        else:
            print("❌ No caption segments generated")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Caption generation test failed: {e}")
        return False

def test_zoom_effects():
    """Test zoom effects calculation"""
    print("\n🔍 Testing zoom effects...")
    
    try:
        from app.services.zoom_effects_service import ZoomEffectsService
        
        # Sample important moments
        sample_moments = [
            {
                "start_time": 2.0,
                "end_time": 4.0,
                "text": "This is a key insight",
                "reason": "key_insight",
                "intensity": "high",
                "keywords": ["key", "insight"]
            }
        ]
        
        zoom_service = ZoomEffectsService()
        
        # Test async function
        async def test_async():
            keyframes = await zoom_service.calculate_zoom_keyframes(sample_moments, 1.3)
            return keyframes
        
        keyframes = asyncio.run(test_async())
        
        if keyframes and len(keyframes) > 0:
            print(f"✅ Generated {len(keyframes)} zoom keyframes")
            for i, kf in enumerate(keyframes):
                print(f"   Keyframe {i+1}: {kf['zoom_start']:.1f}x → {kf['zoom_end']:.1f}x ({kf['start_time']:.1f}s - {kf['end_time']:.1f}s)")
        else:
            print("❌ No zoom keyframes generated")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Zoom effects test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Testing Podcast Processing Setup\n")
    
    tests = [
        ("Import Dependencies", test_imports),
        ("Whisper Initialization", test_whisper_initialization), 
        ("Service Initialization", test_services_initialization),
        ("FFmpeg Availability", test_ffmpeg_availability),
        ("Caption Generation", test_caption_generation),
        ("Zoom Effects", test_zoom_effects)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            failed += 1
    
    print(f"\n📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Podcast processing is ready to use.")
        print("\n📋 Next steps:")
        print("   1. Start the FastAPI server: uvicorn app.main:app --reload")
        print("   2. Start Celery worker: celery -A app.core.celery_app worker --loglevel=info")
        print("   3. Upload a talking-head video and test the /analyze-podcast endpoint")
    else:
        print("❌ Some tests failed. Please fix the issues before using podcast processing.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())