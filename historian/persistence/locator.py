"""Contract wire representation only; this is not a database schema or storage adapter."""
from historian.source_adapter import (
    CoordinatePart,
    EvidenceLocator,
    SourceCoordinate,
    SourceMaterialState,
)


def locator_to_record(locator: EvidenceLocator) -> dict:
    return {
        'source_system': locator.source_system,
        'source_instance_id': locator.source_instance_id,
        'record_id': locator.record_id,
        'version_hash': locator.version_hash,
        'coordinate_system': locator.coordinate.coordinate_system,
        'coordinate_parts': [{'name': p.name, 'value': p.value}
                             for p in locator.coordinate.parts],
        'content_hash': locator.content_hash,
        'material_state': locator.material_state.value,
        'redaction_ref': locator.redaction_ref,
    }


def locator_from_record(record: dict) -> EvidenceLocator:
    # SourceCoordinate validates duplicate names and restores canonical name ordering.
    return EvidenceLocator(
        source_system=record['source_system'], source_instance_id=record['source_instance_id'],
        record_id=record['record_id'], version_hash=record['version_hash'],
        coordinate=SourceCoordinate(record['coordinate_system'], tuple(
            CoordinatePart(p['name'], p['value']) for p in record['coordinate_parts'])),
        content_hash=record['content_hash'],
        material_state=SourceMaterialState(record['material_state']),
        redaction_ref=record['redaction_ref'])
