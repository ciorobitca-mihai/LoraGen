from extensions import supabase_admin

def user_exists(email: str) -> bool:
    res = supabase_admin.auth.admin.list_users()
    return any(
        user.user_metadata and user.user_metadata.get("email") == email for user in res
    )


def return_user(email: str):
    res = supabase_admin.auth.admin.list_users()
    for user in res:
        if user.user_metadata and user.user_metadata.get("email") == email:
            return user
    return None