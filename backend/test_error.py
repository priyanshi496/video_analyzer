import uuid

def test():
    media_assets = [{'id': 'foo'}]
    seg = {"video_idx": "0"}
    try:
        media_asset_id=uuid.UUID(media_assets[seg["video_idx"]]["id"])
    except Exception as e:
        import traceback
        traceback.print_exc()

test()
