# import os
# from io import BytesIO

# from dotenv import load_dotenv
# from minio import Minio
# from minio.error import S3Error


# load_dotenv()


# client = Minio(
#     endpoint=os.environ["MINIO_ENDPOINT"],
#     access_key=os.environ["MINIO_ACCESS_KEY"],
#     secret_key=os.environ["MINIO_SECRET_KEY"],
#     secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
# )

# bucket_name = os.getenv("MINIO_BUCKET", "joblake")


# def main() -> None:
#     try:
#         # Tạo bucket nếu chưa tồn tại
#         if not client.bucket_exists(bucket_name):
#             client.make_bucket(bucket_name)
#             print(f"Created bucket: {bucket_name}")

#         content = "Hello MinIO from Python".encode("utf-8")

#         client.put_object(
#             bucket_name=bucket_name,
#             object_name="test/hello.txt",
#             data=BytesIO(content),
#             length=len(content),
#             content_type="text/plain; charset=utf-8",
#         )

        
        
    

#     except S3Error as exc:
#         print(f"MinIO error: {exc}")
#         raise

    


# if __name__ == "__main__":
#     main()

