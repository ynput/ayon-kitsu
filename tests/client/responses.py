import json
import http

from typing import Any


class RestResponse:
    """REST API Response."""

    def __init__(self, _status_code: int, **data):
        self.status = _status_code
        self.data = data
        # We should never get server error
        assert self.status < 500, data.get("detail", "Internal server error")

    @property
    def detail(self) -> str:
        return self.get("detail", http.HTTPStatus(self.status).description)

    def __repr__(self) -> str:
        return f"<RestResponse: {self.status} ({self.detail})>"

    def __bool__(self) -> bool:
        return 200 <= self.status < 400

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def print(self):
        print(json.dumps(self.data, indent=4))


class GraphQLResponse:
    """GraphQLResponse"""

    def __init__(self, **response) -> None:
        if "code" in response:
            # got rest response instead of gql (maybe unauthorized)
            self.data = {}
            self.errors = [{"message": response["detail"]}]
        else:
            self.data = response.get("data", {})
            self.errors = response.get("errors", [])

    def __bool__(self) -> bool:
        return not self.errors

    def __repr__(self) -> str:
        if self.errors:
            msg = f"errors=\"{self.errors[0]['message']}\""
        else:
            msg = 'status="OK">'
        return f"<GraphQLResponse: {msg}>"

    def __getitem__(self, key: str) -> Any:
        return self.data[key]
