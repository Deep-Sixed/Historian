"""Capability-bound implementations of the application store protocols.

These clients hold no database handle or credentials. Every call is authorized using
its process's kernel UID; constructing a Store never grants a capability.
"""

from types import SimpleNamespace
from historian.libsql_store.client import request
from historian.libsql_store.codec import encode, decode
from historian.source_adapter import (
    EvidenceLocator,
    SourceCoordinate,
    CoordinatePart,
    SourceMaterialState,
)
from historian.persistence.locator import locator_to_record


class Store:
    def __init__(self, socket_path="/run/historian/historian.sock"):
        self.socket_path = socket_path

    def call(self, operation, data):
        result = request(self.socket_path, operation, data)
        if not result["ok"]:
            if result["error"] == "forbidden":
                raise PermissionError("capability denied")
            raise ValueError(result["error"])
        return result["result"]

    def put(self, value):
        return self.call("put_object", {"object": encode(value)})

    def get(self, kind, identity):
        return decode(self.call("get_object", {"kind": kind, "id": identity}))

    put_proposal = put
    put_disposition = put
    put_source_role = put
    put_routing = put
    put_assertion = put
    put_assertion_review = put
    put_resolution = put
    put_resolution_review = put
    put_seed = put
    put_packet = put
    put_adjudication = put
    put_gold = put

    def get_seed(self, identity):
        return self.get("GoldCaseSeed", identity)

    def get_packet(self, identity):
        return self.get("AdjudicationPacket", identity)

    def get_packet_snapshot(self, identity):
        return self.call("get_packet_snapshot", {"id": identity})

    def get_adjudication(self, identity):
        return self.get("BlindAdjudication", identity)

    def get_candidate(self, identity):
        value = self.call("get_candidate", {"id": identity})
        loc = value["locator"]
        if loc["coordinate_system"] != "LINE":
            raise ValueError(
                "legacy line verifier cannot consume structured coordinates"
            )
        parts = {p["name"]: p["value"] for p in loc["coordinate_parts"]}
        return SimpleNamespace(
            id=identity,
            proposed_source_system=loc["source_system"],
            proposed_source_id=loc["record_id"],
            proposed_version_hash=loc["version_hash"],
            proposed_line_start=int(parts["start"]),
            proposed_line_end=int(parts["end"]),
            proposed_quote=value["quote"],
        )

    def put_evidence(self, value):
        loc = EvidenceLocator(
            value["source_system"],
            "configured-corpus",
            value["source_id"],
            value["source_version_hash"],
            SourceCoordinate(
                "LINE",
                (
                    CoordinatePart("start", str(value["line_start"])),
                    CoordinatePart("end", str(value["line_end"])),
                ),
            ),
            value["passage_hash"],
            SourceMaterialState.ORIGINAL,
        )
        return self.call(
            "evidence",
            {
                "id": value["id"],
                "locator": locator_to_record(loc),
                "quote": value["quote"],
                "candidate_id": value.get("derived_from_candidate_id"),
            },
        )
