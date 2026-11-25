
import json
import time
import redis

from .verification_service import process_assignment_verification

REDIS_URL = "redis://localhost:6379/0"

JOB_QUEUE = "verification_jobs"
PROCESSING_QUEUE = "verification_jobs_processing"

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_timeout=15,
    socket_connect_timeout=5,
)


def recover_pending_jobs():
    """Move unfinished jobs back to the main queue."""

    recovered = 0

    while True:
        job = redis_client.rpoplpush(
            PROCESSING_QUEUE,
            JOB_QUEUE,
        )

        if job is None:
            break

        recovered += 1

    print(f"Recovered {recovered} unfinished job(s).")


def run_worker():

    print("Verification worker starting...")

    try:
        redis_client.ping()
        print("Redis connection successful.")

        recover_pending_jobs()

    except redis.RedisError as error:
        print(f"Could not connect to Redis: {error}")
        return

    print("Waiting for verification jobs...")

    while True:

        job = None

        try:
            # Move a job into the processing queue.
            job = redis_client.brpoplpush(
                JOB_QUEUE,
                PROCESSING_QUEUE,
                timeout=5,
            )

            if job is None:
                continue

            data = json.loads(job)

            document_id = int(data["document_id"])

            print(f"Processing document {document_id}...")

            # Run the existing verification pipeline.
            process_assignment_verification(
                document_id=document_id,
                student_id=int(data["student_id"]),
                file_duplicate=bool(data["file_duplicate"]),
                duplicate_reference_id=data["duplicate_reference_id"],
            )

            # Remove the job after processing returns.
            redis_client.lrem(
                PROCESSING_QUEUE,
                1,
                job,
            )

            print(f"Document {document_id} processing finished.")

        except KeyboardInterrupt:
            print("Worker stopped.")
            break

        except Exception as error:
            print(f"Worker error: {error}")

            if job is not None:
                print(
                    "Job retained in processing queue. "
                    "It can be recovered when the worker restarts."
                )

            time.sleep(2)


if __name__ == "__main__":
    run_worker()
