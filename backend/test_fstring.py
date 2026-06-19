def test(segments, removed_clips):
    return f"""
- CLIP COUNT CHECK: There are {len(segments)} clips (indices 0 to {len(segments)-1}). Your 'order' array MUST contain exactly {len(segments)} minus len(removed_clips) indices. If you have 12 clips and removed 0, 'order' MUST have 12 entries.
"""
print(test([1,2,3], []))
