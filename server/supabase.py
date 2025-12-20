"""Supabase client for Library feature"""
import os
import uuid
from supabase import create_client, Client

_client: Client | None = None


def get_supabase() -> Client:
    """Get or create Supabase client (lazy initialization)"""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables required")
        _client = create_client(url, key)
    return _client


def upload_audio(device_id: str, sample_id: str, wav_bytes: bytes) -> str:
    """Upload WAV to Supabase Storage, return public URL"""
    client = get_supabase()
    path = f"samples/{device_id}/{sample_id}.wav"
    client.storage.from_("audio").upload(
        path,
        wav_bytes,
        {"content-type": "audio/wav"}
    )
    return client.storage.from_("audio").get_public_url(path)


def save_sample_metadata(data: dict) -> dict:
    """Insert sample metadata into database, return created row"""
    client = get_supabase()
    result = client.table("samples").insert(data).execute()
    return result.data[0]


def get_samples(device_id: str, limit: int = 20, offset: int = 0) -> tuple[list, int]:
    """Get samples for a device, returns (samples, total_count)"""
    client = get_supabase()

    # Get total count
    count_result = client.table("samples").select("id", count="exact").eq("device_id", device_id).execute()
    total = count_result.count or 0

    # Get samples with pagination
    result = client.table("samples")\
        .select("*")\
        .eq("device_id", device_id)\
        .order("created_at", desc=True)\
        .range(offset, offset + limit - 1)\
        .execute()

    return result.data, total


def delete_sample(sample_id: str, device_id: str) -> bool:
    """Delete sample if owned by device_id, returns success"""
    client = get_supabase()

    # Verify ownership
    sample = client.table("samples").select("*").eq("id", sample_id).single().execute()
    if not sample.data or sample.data.get("device_id") != device_id:
        return False

    # Delete from storage
    path = f"samples/{device_id}/{sample_id}.wav"
    try:
        client.storage.from_("audio").remove([path])
    except Exception:
        pass  # Storage file may not exist

    # Delete from database
    client.table("samples").delete().eq("id", sample_id).execute()
    return True
