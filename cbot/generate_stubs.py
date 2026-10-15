import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

MAIN_STUB = """using cAlgo.API;

namespace cAlgo.Robots
{{
    public enum SignalModel
    {{
{members}
    }}

    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class AiForexSignal : Robot
    {{
        [Parameter("Backend URL", DefaultValue = "https://your-backend.example.com")]
        public string BackendUrl {{ get; set; }}

        [Parameter("API key", DefaultValue = "")]
        public string ApiKey {{ get; set; }}

        [Parameter("Model", DefaultValue = SignalModel.{default})]
        public SignalModel Model {{ get; set; }}

        [Parameter("Timeframe 1")]
        public TimeFrame TimeframeOne {{ get; set; }}

        [Parameter("Timeframe 2")]
        public TimeFrame TimeframeTwo {{ get; set; }}

        [Parameter("Timeframe 3")]
        public TimeFrame TimeframeThree {{ get; set; }}
    }}
}}
"""

SMOKE_STUB = """using cAlgo.API;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class SmokeTest : Robot
    {
        [Parameter("Backend URL", DefaultValue = "https://your-backend.example.com")]
        public string BackendUrl { get; set; }

        [Parameter("API key", DefaultValue = "")]
        public string ApiKey { get; set; }
    }
}
"""


def generate(config_path: Path, out_dir: Path) -> None:
    settings = yaml.safe_load(config_path.read_text())
    keys = [model["key"] for model in settings["models"]["allowed"]]
    members = ",\n".join(f"        {key}" for key in keys)
    (out_dir / "AiForexSignal.cs").write_text(MAIN_STUB.format(members=members, default=settings["models"]["default"]))
    (out_dir / "SmokeTest.cs").write_text(SMOKE_STUB)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cbot"
    generate(ROOT / "config" / "settings.yaml", target)
