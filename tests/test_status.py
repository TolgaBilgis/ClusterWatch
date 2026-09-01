from clusterwatch.config import ControllerSettings
from clusterwatch.controller.status import evaluate_status


def test_gpu_temperature_can_trigger_warning():
    settings = ControllerSettings(temperature_warning_c=80)
    node = {"last_seen": 100.0}
    latest = {
        "cpu_percent": 10,
        "memory_percent": 10,
        "disk_percent": 10,
        "temperatures_c": {},
        "gpu": {"temperature_c": 84},
    }
    status, reasons = evaluate_status(node, latest, settings, now=101)
    assert status == "WARNING"
    assert reasons == ["GPU 84.0°C ≥ 80.0°C"]


def test_offline_takes_precedence_over_warning():
    settings = ControllerSettings(offline_timeout_seconds=10, cpu_warning_percent=85)
    node = {"last_seen": 100.0}
    latest = {"cpu_percent": 99, "memory_percent": 10, "disk_percent": 10, "temperatures_c": {}, "gpu": {}}
    status, reasons = evaluate_status(node, latest, settings, now=111)
    assert status == "OFFLINE"
    assert reasons == ["No heartbeat for 11s"]

