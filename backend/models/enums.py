from enum import IntEnum


class ToolType(IntEnum):
    LLM = 0
    Endpoint = 1
    Pause = 2
    Agent = 3
    Pipeline = 4
    If = 5
    Parallel = 6
    End = 7
    Wait = 8
    Start = 9
    LoopCounter = 10
    AskUser = 11
    FileUpload = 12
    FileDownload = 13
    Task = 14


class PropertyType(IntEnum):
    TEXT = 0
    NUMBER = 1
    BOOLEAN = 2
    FILE = 3
    DATE = 4
    PASSWORD = 5
    SELECT = 6


class PipelineStatusType(IntEnum):
    Pending = 0
    Running = 1
    Completed = 2
    Failed = 3
    Paused = 4
    WaitingForInput = 5


class TriggerType(IntEnum):
    Cron = 0
    FileWatcher = 1
    Webhook = 2
    RSS = 3
    Custom = 4


class EndpointMethod(IntEnum):
    GET = 0
    POST = 1
    PUT = 2
    DELETE = 3
