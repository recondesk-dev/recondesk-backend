import boto3
import os
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)

# Checkpoint 1 — Upload
s3.put_object(
    Bucket=os.getenv("R2_BUCKET_NAME"),
    Key="test/hello.json",
    Body=b'{"status": "r2_working"}',
    ContentType="application/json",
)
print("✅ Checkpoint 1: Upload done")

# Checkpoint 2 — Signed URL
url = s3.generate_presigned_url(
    "get_object",
    Params={
        "Bucket": os.getenv("R2_BUCKET_NAME"),
        "Key": "test/hello.json"
    },
    ExpiresIn=3600,
)
print(f"✅ Checkpoint 2: Signed URL:\n{url}")