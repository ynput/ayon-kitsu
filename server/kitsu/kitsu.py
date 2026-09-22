from typing import Literal

import httpx


class KitsuLoginException(Exception):
    pass


class Kitsu:
    LoginException = KitsuLoginException

    def __init__(self, server: str, email: str, password: str):
        self.email = email
        self.password = password
        self.base_url = server
        self.token = None

    async def login(self):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/auth/login",
                    data={"email": self.email, "password": self.password},
                )
        except httpx.HTTPError as e:
            raise KitsuLoginException(
                f"Could not reach Kitsu at {self.base_url}: {e}"
            ) from e

        try:
            token = response.json().get("access_token")
        except ValueError:
            # A proxy or a crashing Kitsu answers html, not the expected json.
            token = None

        if not token:
            raise KitsuLoginException(
                f"Could not login to Kitsu at {self.base_url} as"
                f" {self.email} (status {response.status_code}):"
                f" {response.text[:500]}"
            )
        self.token = token

    async def logout(self):
        if not self.token:
            return
        async with httpx.AsyncClient() as client:
            await client.get(
                f"{self.base_url}/api/auth/logout",
                headers={"Authorization": f"Bearer {self.token}"},
            )

    async def ensure_login(self):
        if not self.token:
            await self.login()
            return

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/auth/authenticated",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        except httpx.HTTPError as e:
            raise KitsuLoginException(
                f"Could not reach Kitsu at {self.base_url}: {e}"
            ) from e

        if response.status_code == 401:
            await self.login()
        elif response.is_error:
            # The body is whatever Kitsu chose to answer, so keep enough of
            # it to diagnose and no more.
            raise KitsuLoginException(
                "Could not login to Kitsu (server error"
                f" {response.status_code}): {response.text[:500]}"
            )

    async def request(
        self,
        method: Literal["get", "post", "put", "delete", "patch"],
        endpoint: str,
        headers: dict[str, str] | None = None,
        **kwargs,
    ) -> httpx.Response:
        await self.ensure_login()
        if headers is None:
            headers = {}
        headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                f"{self.base_url}/api/{endpoint}",
                headers=headers,
                **kwargs,
            )
        return response

    async def get(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("get", endpoint, **kwargs)

    async def post(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("post", endpoint, **kwargs)

    async def put(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("put", endpoint, **kwargs)

    async def delete(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("delete", endpoint, **kwargs)

    async def patch(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("patch", endpoint, **kwargs)
