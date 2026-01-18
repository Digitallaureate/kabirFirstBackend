# # from firebase_admin import firestore, storage, credentials, initialize_app, get_app
# # import firebase_admin

# # def get_project_b_app():
# #     try:
# #         return get_app(name="projectB")
# #     except ValueError:
# #         cred = credentials.Certificate("ecostory-service-account.json")
# #         return initialize_app(cred, {
# #             'storageBucket': 'your-bucket-name.appspot.com'
# #         }, name="projectB")

# # def get_project_b_firestore():
# #     return firestore.client(get_project_b_app())

# # def get_project_b_storage_bucket():
# #     return storage.bucket(app=get_project_b_app())

# from firebase_admin import firestore, storage, credentials, initialize_app, get_app
# import os


# def get_project_b_app():
#     try:
#         # If projectB is already initialized, just reuse it
#         return get_app(name="projectB")
#     except ValueError:
#         # First, try Application Default Credentials (works on Cloud Functions)
#         try:
#             cred = credentials.ApplicationDefault()
#             print("[firebase_setup] Using ApplicationDefault credentials for projectB")
#             return initialize_app(
#                 cred,
#                 {
#                     "storageBucket": "your-bucket-name.appspot.com",  # TODO: replace with real bucket
#                 },
#                 name="projectB",
#             )
#         except Exception:
#             # If ADC is not available (local CLI), fall back to JSON file
#             functions_dir = os.path.dirname(__file__)       # .../initial_project/functions
#             project_root = os.path.dirname(functions_dir)   # .../initial_project

#             possible_paths = [
#                 os.path.join(functions_dir, "ecostory-service-account.json"),   # functions/
#                 os.path.join(project_root, "ecostory-service-account.json"),    # project root
#             ]

#             cred_path = None
#             for p in possible_paths:
#                 if os.path.exists(p):
#                     cred_path = p
#                     break

#             if cred_path is None:
#                 raise FileNotFoundError(
#                     "Service account JSON not found for projectB. Tried:\n"
#                     + "\n".join(possible_paths)
#                     + "\nOr set GOOGLE_APPLICATION_CREDENTIALS env var."
#                 )

#             print(f"[firebase_setup] Using service account for projectB at: {cred_path}")

#             cred = credentials.Certificate(cred_path)
#             return initialize_app(
#                 cred,
#                 {
#                     "storageBucket": "your-bucket-name.appspot.com",  # TODO: replace with real bucket
#                 },
#                 name="projectB",
#             )


# def get_project_b_firestore():
#     return firestore.client(get_project_b_app())


# def get_project_b_storage_bucket():
#     return storage.bucket(app=get_project_b_app())

from firebase_admin import firestore, storage, credentials, initialize_app, get_app
import os


def _get_service_account_path() -> str:
    """
    Find ecostory-service-account.json in either:
    - project_root/ecostory-service-account.json
    - functions/ecostory-service-account.json
    """
    functions_dir = os.path.dirname(__file__)       # .../initial_project/functions
    project_root = os.path.dirname(functions_dir)   # .../initial_project

    possible_paths = [
        os.path.join(functions_dir, "ecostory-service-account.json"),
        os.path.join(project_root, "ecostory-service-account.json"),
    ]

    for p in possible_paths:
        if os.path.exists(p):
            print(f"[firebase_setup] Using service account for projectB at: {p}")
            return p

    raise FileNotFoundError(
        "Service account JSON not found for projectB. Tried:\n"
        + "\n".join(possible_paths)
    )


def get_project_b_app():
    try:
        # Reuse if already initialized
        return get_app(name="projectB")
    except ValueError:
        # Initialize explicitly with service-account JSON
        cred_path = _get_service_account_path()
        cred = credentials.Certificate(cred_path)

        return initialize_app(
            cred,
            {
                # TODO: put your actual bucket name here:
                "storageBucket": "your-bucket-name.appspot.com",
            },
            name="projectB",
        )


def get_project_b_firestore():
    return firestore.client(get_project_b_app())


def get_project_b_storage_bucket():
    return storage.bucket(app=get_project_b_app())
