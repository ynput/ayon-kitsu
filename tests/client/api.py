import json
import requests
import platform
import codenamize
import uuid

from typing import Any, Dict
from nxtools import logging

from .responses import RestResponse, GraphQLResponse


def get_ayon_headers() -> Dict[str, str]:
    platform_info = platform.system().lower()
    assert platform_info in ("linux", "windows", "darwin")
    client_id = codenamize.codenamize(str(uuid.getnode()), 5)
    return {
        "x-ayon-platform": platform_info,
        "x-ayon-version": "1.0.0",
        "x-ayon-client-id": client_id,
        "x-ayon-hostname": platform.node(),
    }


class API:
    """OpenPype API client"""

    def __init__(self, server_url: str, access_token: str, debug: bool = False):
        self.server_url = server_url.rstrip("/")
        self.access_token = access_token
        self.debug = debug
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.access_token}",
            }
        )

    def __bool__(self):
        return not not self.access_token

    @classmethod
    def login(
        cls,
        name: str,
        password: str,
        server_url: str = "http://localhost:5000",
    ) -> "API":
        server_url = server_url.rstrip("/")
        response = requests.post(
            server_url + "/api/auth/login", json={"name": name, "password": password}
        )
        data = response.json()
        return cls(server_url, data.get("token", ""))

    def logout(self) -> RestResponse:
        if not self.access_token:
            return
        return self.post("auth/logout")

    def gql(self, query: str, **kwargs: Dict[str, Any]) -> GraphQLResponse:
        """Execute a GraphQL query."""
        payload = {"query": query, "variables": kwargs}
        response = self.session.post(self.server_url + "/graphql", json=payload)
        return GraphQLResponse(**response.json())

    def _request(self, function: callable, url: str, **kwargs) -> RestResponse:
        """Do an authenticated HTTP request.

        This private method is used by get/post/put/patch/delete
        """
        try:
            response = function(url, **kwargs)
        except ConnectionRefusedError:
            response = RestResponse(
                500, detail="Unable to connect the server. Connection refused"
            )
        except requests.exceptions.ConnectionError:
            response = RestResponse(
                500, detail="Unable to connect the server. Connection error"
            )
        else:
            if response.text == "":
                data = None
                response = RestResponse(response.status_code)
            else:
                try:
                    data = response.json()
                except json.JSONDecodeError:
                    logging.error(response.text)
                    response = RestResponse(
                        500, detail=f"The response is not a JSON: {response.text}"
                    )
                else:
                    if type(data) == dict:
                        response = RestResponse(response.status_code, **data)
                    else:
                        response = RestResponse(200)
                        response.data = data
        if self.debug:
            if response:
                logging.goodnews(response)
            else:
                logging.error(response)
        return response

    def raw_post(self, endpoint: str, mime: str, data: bytes) -> RestResponse:
        endpoint = endpoint.strip("/")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(
            self.session.post, url, data=data, headers={"Content-Type": mime}
        )

    def raw_put(self, endpoint: str, mime: str, data: bytes) -> RestResponse:
        endpoint = endpoint.strip("/")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(
            self.session.put, url, data=data, headers={"Content-Type": mime}
        )

    def raw_get(self, endpoint: str, **kwargs) -> RestResponse:
        endpoint = endpoint.strip("/")
        url = f"{self.server_url}/api/{endpoint}"
        print(url)
        response = self.session.get(url, params=kwargs)
        return response.content

    def get(self, endpoint: str, **kwargs) -> RestResponse:
        endpoint = endpoint.strip("/")
        if self.debug:
            logging.info(f"Executing [GET] {endpoint}")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(self.session.get, url, params=kwargs)

    def post(self, endpoint: str, **kwargs) -> RestResponse:
        endpoint = endpoint.strip("/")
        if self.debug:
            logging.info(f"Executing [POST] {endpoint}")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(self.session.post, url, json=kwargs)

    def put(self, endpoint: str, **kwargs) -> RestResponse:
        endpoint = endpoint.strip("/")
        if self.debug:
            logging.info(f"Executing [PUT] {endpoint}")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(self.session.put, url, json=kwargs)

    def patch(self, endpoint: str, **kwargs) -> RestResponse:
        endpoint = endpoint.strip("/")
        if self.debug:
            logging.info(f"Executing [PATCH] {endpoint}")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(self.session.patch, url, json=kwargs)

    def delete(self, endpoint: str, **kwargs) -> RestResponse:
        endpoint = endpoint.strip("/")
        if self.debug:
            logging.info(f"Executing [DELETE] {endpoint}")
        url = f"{self.server_url}/api/{endpoint}"
        return self._request(self.session.delete, url, params=kwargs)
