import asyncio
from app.core.database import engine
from app.models.domain import AnalysisJob
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

async def main():
    async with AsyncSession(engine) as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.story_summary != None).order_by(AnalysisJob.created_at.desc()).limit(5))
        jobs = result.scalars().all()
        for job in jobs:
            print("\n" + "="*80)
            print(f"=== STORY NARRATIVE (Job ID: {job.id}) ===")
            print("="*80 + "\n")
            print(job.story_summary)
            print("\n" + "="*80)
        if not jobs:
            print("No jobs with story_summary found.")

if __name__ == "__main__":
    asyncio.run(main())
