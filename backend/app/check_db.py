import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import json

async def main():
    engine = create_async_engine('postgresql+asyncpg://user:password@localhost:5434/video_analyzer')
    async with engine.connect() as conn:
        print("--- Last Completed Job Details ---")
        result = await conn.execute(text("SELECT id, project_id, status, progress FROM analysis_jobs WHERE status = 'COMPLETED' ORDER BY created_at DESC LIMIT 1"))
        job = result.first()
        if not job:
            print("No completed jobs found.")
            return
        
        job_id = job[0]
        project_id = job[1]
        print(f"Job ID: {job_id}, Project ID: {project_id}, Status: {job[2]}, Progress: {job[3]}")
        
        print("\n--- Analyzed Clips in Job ---")
        result = await conn.execute(text(f"SELECT id, start_sec, end_sec, story_position, metadata_json FROM analyzed_clips WHERE job_id = '{job_id}' ORDER BY story_position"))
        clips = result.all()
        for c in clips:
            meta = json.loads(c[4]) if isinstance(c[4], str) else c[4]
            dur = c[2] - c[1]
            print(f"Pos {c[3]}: [{c[1]:.2f}s - {c[2]:.2f}s] (dur={dur:.2f}s) | Location: {meta.get('location_tag')} | Used: {meta.get('is_used')} | Trans: {meta.get('next_transition')} | TransDur: {meta.get('next_transition_duration')}")

if __name__ == '__main__':
    asyncio.run(main())
