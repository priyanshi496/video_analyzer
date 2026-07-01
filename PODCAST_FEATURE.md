# Podcast Video Processing Feature 🎙️

## Overview

This feature adds intelligent talking-head video processing to the existing AI Video Analyzer. It takes podcast/interview videos and automatically:

1. **Transcribes** every word with precise timestamps using Whisper
2. **Generates smart captions** (3-4 words per line, CapCut style)  
3. **Detects important moments** using LLM analysis
4. **Adds auto-zoom effects** on key insights and emotional peaks
5. **Renders final video** with captions + zoom effects

## 🌟 Key Features

### 📝 Smart Transcription
- **Whisper Integration**: Uses `faster-whisper` (4x faster than regular Whisper)
- **Word-level Timestamps**: Precise timing for each word
- **Model Size**: Optimized "small" model for 16GB MacBook Air
- **Language Support**: Auto-detection with 20+ languages

### 🎬 Intelligent Captions
- **Line-by-Line Style**: 3-4 words per caption (like viral TikToks/Reels)
- **Natural Breaks**: Respects punctuation and speech pauses
- **Professional Styling**: Clean fonts with background boxes
- **Flexible Positioning**: Bottom, top, or center placement

### 🧠 AI Moment Detection
- **LLM Analysis**: Uses free models (Gemini, Llama-3, Phi-3)
- **Key Moment Types**: 
  - Strong opinions ("This is completely wrong")
  - Statistics ("300% growth", "$1M revenue")
  - Key insights ("The breakthrough moment")  
  - Emotional peaks (excitement, frustration)
  - Conclusions ("The answer is simple")
- **Smart Filtering**: Prevents over-zooming with timing constraints

### 🔍 Auto-Zoom Effects  
- **Dynamic Zoom**: Smooth 1.0x → 1.3x transitions
- **Context-Aware**: Zoom intensity based on moment importance
- **Professional Timing**: 0.5s transitions, minimum 2s hold
- **FFmpeg Integration**: Uses `zoompan` filter for smooth effects

## 🛠️ Technical Implementation

### Backend Services
```
backend/app/services/
├── podcast_service.py          # Main orchestrator
├── transcription_service.py    # Whisper integration  
├── caption_service.py          # Smart caption generation
├── moment_detection_service.py # LLM analysis
└── zoom_effects_service.py     # Auto-zoom calculations
```

### API Endpoints
```
POST /api/v1/projects/{id}/analyze-podcast
GET  /api/v1/jobs/{id}/transcript  
POST /api/v1/jobs/{id}/regenerate-captions
GET  /api/v1/projects/{id}/podcast-timeline
```

### Processing Pipeline
1. **Upload** talking-head video to project
2. **Extract** audio track with FFmpeg
3. **Transcribe** with Whisper (word timestamps)
4. **Generate** line-by-line captions (3-4 words)
5. **Analyze** transcript with LLM → find key moments
6. **Calculate** zoom keyframes for important moments
7. **Render** final video with FFmpeg (captions + zoom)
8. **Upload** result to storage

## 📊 Performance

### Whisper Model Sizes
| Model  | Size  | Speed      | Accuracy  | RAM Usage |
|--------|-------|------------|-----------|-----------|
| tiny   | 39 MB | Very Fast  | Basic     | 1-2 GB    |
| small  | 244 MB| Medium     | Good      | 2-4 GB    |
| base   | 74 MB | Fast       | Decent    | 1-3 GB    |

**Recommended**: `small` model for 16GB MacBook Air (optimal speed/quality)

### Processing Times
- **Transcription**: ~8-12 seconds for 1-minute video
- **LLM Analysis**: ~2-3 seconds for transcript
- **Video Rendering**: ~30-40 seconds for 1-minute final video
- **Total**: ~45-60 seconds for complete processing

## 🚀 Usage

### 1. Upload Video
```bash
# Upload talking-head video to project
curl -X POST /api/v1/projects/{project_id}/media \
  -F "file=@podcast_video.mp4"
```

### 2. Start Processing
```bash
curl -X POST /api/v1/projects/{project_id}/analyze-podcast \
  -H "Content-Type: application/json" \
  -d '{
    "caption_style": "line_by_line",
    "words_per_line": 4,
    "zoom_detection": "auto_llm", 
    "zoom_intensity": 1.3,
    "caption_position": "bottom"
  }'
```

### 3. Monitor Progress
```bash
curl /api/v1/jobs/{job_id}
# Returns: status, progress, error_message
```

### 4. Get Results
```bash
curl /api/v1/projects/{project_id}/podcast-timeline
# Returns: transcript, captions, zoom markers, final video URL
```

## 💰 Cost Analysis

### Completely Free Stack
- **Transcription**: `faster-whisper` (runs locally, ₹0 cost)
- **LLM Analysis**: Free OpenRouter models
  - `google/gemini-flash-1.5:free`
  - `meta-llama/llama-3-8b-instruct:free` 
  - `microsoft/phi-3-mini-128k-instruct:free`
- **Video Processing**: FFmpeg (open source, ₹0 cost)

**Total Cost Per Video**: ₹0 🎉

## 🔧 Installation

### 1. Install Dependencies
```bash
cd backend
pip install faster-whisper openai-whisper nest-asyncio
```

### 2. Verify FFmpeg
```bash
ffmpeg -version
# Ensure drawtext and zoompan filters available
```

### 3. Test Whisper
```bash
python -c "from faster_whisper import WhisperModel; print('✅ Whisper ready')"
```

## 📈 Example Use Cases

### 1. Podcast Highlights
- 60-minute podcast → 10 key moments with zoom
- Auto-generated captions for social media clips
- Perfect for YouTube Shorts, TikTok, Instagram Reels

### 2. Interview Processing  
- Long-form interviews → highlight reels
- Professional captions for accessibility
- Zoom on statistics and key quotes

### 3. Educational Content
- Lecture videos → emphasize important concepts  
- Tutorial highlights with visual emphasis
- Student-friendly caption formatting

## 🎯 Caption Styles

### Line-by-Line (Recommended)
```
"This is a game"
"changing insight that"  
"will transform your business"
```

### Word-by-Word (Karaoke)
```  
"This" → "is" → "a" → "game" → "changing"...
```

## 🔮 Future Enhancements

### Phase 2 Features
- **Custom Fonts**: Upload brand fonts
- **Multi-Language**: Support Hindi, Spanish, etc.
- **Speaker Detection**: Multi-person zoom focus
- **Custom Zoom Areas**: Face tracking vs full-body
- **Brand Colors**: Custom caption styling
- **Batch Processing**: Multiple videos at once

### AI Improvements  
- **Emotion Detection**: Voice tone analysis for zoom timing
- **Topic Segmentation**: Chapter-based processing  
- **Sentiment Analysis**: Zoom on positive/negative peaks
- **Custom Prompts**: User-defined moment detection rules

---

## 📞 Support

This feature integrates seamlessly with the existing video analyzer infrastructure. All current project management, storage, and authentication systems work unchanged.

For issues or feature requests, check the main project documentation or create an issue in the repository.