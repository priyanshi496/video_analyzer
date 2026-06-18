import httpx
import uuid
import sys

BASE_URL = "http://localhost:8000/api/v1"

def test_auth_flow():
    # Setup test credentials
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    test_password = "securepassword123"

    print(f"1. Registering test user: {test_email}...")
    try:
        response = httpx.post(
            f"{BASE_URL}/auth/register",
            json={"email": test_email, "password": test_password},
            timeout=10.0
        )
    except Exception as e:
        print(f"Error connecting to backend: {e}")
        print("Make sure your FastAPI server is running on localhost:8000")
        sys.exit(1)
        
    if response.status_code != 201:
        print(f"FAIL: Registration failed with status {response.status_code}: {response.text}")
        sys.exit(1)
    
    print("SUCCESS: Registration successful.")

    print("\n2. Trying to register duplicate email...")
    dup_resp = httpx.post(
        f"{BASE_URL}/auth/register",
        json={"email": test_email, "password": "anotherpassword"},
        timeout=10.0
    )
    if dup_resp.status_code == 400:
        print("SUCCESS: Duplicate registration correctly rejected with 400 Bad Request.")
    else:
        print(f"FAIL: Duplicate registration allowed or returned incorrect status {dup_resp.status_code}")
        sys.exit(1)

    print("\n3. Logging in to get access token...")
    login_resp = httpx.post(
        f"{BASE_URL}/auth/token",
        data={"username": test_email, "password": test_password},
        timeout=10.0
    )
    if login_resp.status_code != 200:
        print(f"FAIL: Login failed with status {login_resp.status_code}: {login_resp.text}")
        sys.exit(1)
    
    token_data = login_resp.json()
    token = token_data.get("access_token")
    if not token:
        print("FAIL: No access token in login response")
        sys.exit(1)
    print("SUCCESS: Token retrieved.")

    headers = {"Authorization": f"Bearer {token}"}

    print("\n4. Accessing /auth/me with token...")
    me_resp = httpx.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10.0)
    if me_resp.status_code != 200:
        print(f"FAIL: /auth/me returned status {me_resp.status_code}: {me_resp.text}")
        sys.exit(1)
    print(f"SUCCESS: Current user verified: {me_resp.json().get('email')}")

    print("\n5. Accessing protected endpoint without token...")
    no_token_resp = httpx.post(f"{BASE_URL}/projects/", json={"name": "Test project"}, timeout=10.0)
    if no_token_resp.status_code == 401:
        print("SUCCESS: Anonymous project creation correctly blocked with 401 Unauthorized.")
    else:
        print(f"FAIL: Anonymous project creation allowed or returned status {no_token_resp.status_code}")
        sys.exit(1)

    print("\n6. Creating project with valid token...")
    proj_resp = httpx.post(
        f"{BASE_URL}/projects/",
        json={"name": "Authenticated test project"},
        headers=headers,
        timeout=10.0
    )

    if proj_resp.status_code != 201:
        print(f"FAIL: Project creation failed with status {proj_resp.status_code}: {proj_resp.text}")
        sys.exit(1)
    
    proj_data = proj_resp.json()
    project_id = proj_data.get("id")
    print(f"SUCCESS: Project created: {project_id}")

    print("\n7. Patching/updating project name...")
    patch_resp = httpx.patch(
        f"{BASE_URL}/projects/{project_id}",
        json={"name": "Renamed project"},
        headers=headers,
        timeout=10.0
    )
    if patch_resp.status_code != 200:
        print(f"FAIL: Project patch failed with status {patch_resp.status_code}: {patch_resp.text}")
        sys.exit(1)
    
    updated_data = patch_resp.json()
    if updated_data.get("name") != "Renamed project":
        print(f"FAIL: Project patch did not update name correctly: {updated_data}")
        sys.exit(1)
    print("SUCCESS: Project patched successfully.")

    print("\n8. Accessing another user's project (simulated via anonymous or invalid header)...")
    bad_headers = {"Authorization": "Bearer invalidtoken123"}
    bad_resp = httpx.get(f"{BASE_URL}/projects/{project_id}/media", headers=bad_headers, timeout=10.0)
    if bad_resp.status_code == 401:
        print("SUCCESS: Access with invalid token blocked with 401 Unauthorized.")
    else:
        print(f"FAIL: Access with invalid token allowed or returned status {bad_resp.status_code}")
        sys.exit(1)


    print("\nALL AUTHENTICATION FLOW TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_auth_flow()
