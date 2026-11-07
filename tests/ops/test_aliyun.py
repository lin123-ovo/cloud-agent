import json
from datetime import timedelta
from types import SimpleNamespace
import pytest
from cloudops.providers import AliyunProvider, CloudError, provider
from tests.ops.test_rules import resource, START, END


class Response:
    def __init__(self, data):
        self.body = SimpleNamespace(to_map=lambda: data)


class Client:
    def __init__(self, **responses):
        self.responses = responses
        self.calls = []

    def __getattr__(self, name):
        def call(request, runtime):
            self.calls.append((name, request.to_map(), runtime))
            data = self.responses[name].pop(0)
            if isinstance(data, Exception):
                raise data
            return Response(data)

        return call


def adapter(ecs=None, cms=None):
    return AliyunProvider(ecs or Client(), cms or Client())


def instance(id):
    return {
        "InstanceId": id,
        "InstanceType": "ecs.g8a.4xlarge",
        "Cpu": 16,
        "Memory": 65536,
        "Status": "Running",
    }


def test_instance_pagination_and_empty_result():
    c = Client(
        describe_instances_with_options=[
            {"Instances": {"Instance": [instance("i-1")]}, "NextToken": "next"},
            {"Instances": {"Instance": [instance("i-2")]}},
        ]
    )
    rows = adapter(c).resources("cn-beijing")
    assert [r.id for r in rows] == ["i-1", "i-2"] and rows[0].memory_gb == 64
    assert c.calls[1][1]["NextToken"] == "next"
    assert c.calls[0][2].autoretry is False
    assert (
        adapter(Client(describe_instances_with_options=[{}])).resources("cn-beijing")
        == []
    )


def test_monitoring_pages_and_memory_absence():
    c = Client(
        describe_metric_list_with_options=[
            {
                "Success": True,
                "Datapoints": json.dumps(
                    [
                        {
                            "timestamp": int(START.timestamp() * 1000),
                            "Average": 3,
                            "Maximum": 95,
                        }
                    ]
                ),
                "NextToken": "p2",
            },
            {
                "Success": True,
                "Datapoints": json.dumps(
                    [
                        {
                            "timestamp": int(
                                (START + timedelta(minutes=5)).timestamp() * 1000
                            ),
                            "Average": 2,
                            "Maximum": 4,
                        }
                    ]
                ),
            },
            {"Success": True, "Datapoints": "[]"},
        ]
    )
    points = adapter(cms=c).samples(resource(), START, END)
    assert len(points) == 2 and points[0].memory is None and points[0].cpu_max == 95
    assert c.calls[1][1]["NextToken"] == "p2"
    assert c.calls[0][1]["Period"] == "300"


class SDKError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("secret-access-token")


@pytest.mark.parametrize(
    "code", ["Forbidden.RAM", "InvalidAccessKeyId.NotFound", "SignatureDoesNotMatch"]
)
def test_auth_error_redaction(code):
    with pytest.raises(CloudError) as error:
        adapter(Client(describe_instances_with_options=[SDKError(code)])).resources(
            "cn-beijing"
        )
    assert error.value.code == "AccessDenied" and "secret" not in str(error.value)


@pytest.mark.parametrize("error", [SDKError("Throttling"), TimeoutError("secret")])
def test_bounded_retry(error):
    c = Client(describe_instances_with_options=[error, {}])
    assert adapter(c).resources("cn-beijing") == [] and len(c.calls) == 2


def test_timeout_after_retry():
    c = Client(
        describe_instances_with_options=[TimeoutError("secret"), TimeoutError("secret")]
    )
    with pytest.raises(CloudError):
        adapter(c).resources("cn-beijing")
    assert len(c.calls) == 2


def test_only_compute_price_and_platform():
    price = {
        "Currency": "CNY",
        "OriginalPrice": 99,
        "DetailInfos": {
            "DetailInfo": [
                {"Resource": "instanceType", "OriginalPrice": 4},
                {"Resource": "systemDisk", "OriginalPrice": 95},
            ]
        },
    }
    c = Client(describe_price_with_options=[{"PriceInfo": {"Price": price}}])
    q = adapter(c).quote(resource(), "ecs.g8a.4xlarge")
    assert (
        q.amount == 4
        and c.calls[0][1]["Platform"] == "Linux"
        and c.calls[0][1]["PriceUnit"] == "Hour"
    )


def test_price_without_compute_breakdown_is_rejected():
    with pytest.raises(CloudError):
        adapter(
            Client(
                describe_price_with_options=[
                    {"PriceInfo": {"Price": {"OriginalPrice": 99, "Currency": "CNY"}}}
                ]
            )
        ).quote(resource(), "target")


def test_configuration_and_region_never_fall_back(monkeypatch):
    monkeypatch.setenv("ALIYUN_REGIONS", "cn-beijing")
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    with pytest.raises(CloudError, match="尚未配置"):
        provider("aliyun", "cn-beijing")
    with pytest.raises(CloudError):
        provider("demo", "forbidden")
    with pytest.raises(CloudError):
        provider("unknown", "cn-beijing")


def test_disallow_mutation():
    with pytest.raises(CloudError):
        adapter()._call("ecs", "stop_instance")


def test_instance_type_pagination():
    spec = {
        "InstanceTypeId": "ecs.g8a.2xlarge",
        "InstanceTypeFamily": "ecs.g8a",
        "CpuCoreCount": 8,
        "MemorySize": 32,
    }
    c = Client(
        describe_instance_types_with_options=[
            {"InstanceTypes": {"InstanceType": []}, "NextToken": "second"},
            {"InstanceTypes": {"InstanceType": [spec]}},
        ]
    )
    assert adapter(c).specs(resource())[0]["cpu"] == 8
    assert c.calls[1][1]["NextToken"] == "second"


def test_monitoring_failure_is_explicit():
    c = Client(
        describe_metric_list_with_options=[{"Success": False, "Datapoints": "[]"}]
    )
    with pytest.raises(CloudError):
        adapter(cms=c).samples(resource(), START, END)
