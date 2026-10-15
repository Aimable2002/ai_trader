using cAlgo.API;

namespace cAlgo.Robots
{
    public enum SignalModel
    {
        Opus55,
        Sonnet55,
        Gemini4Argon,
        Gpt6Astra,
        Grok46,
        DeepseekV41Flash
    }

    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class AiForexSignal : Robot
    {
        [Parameter("Backend URL", DefaultValue = "https://your-backend.example.com")]
        public string BackendUrl { get; set; }

        [Parameter("API key", DefaultValue = "")]
        public string ApiKey { get; set; }

        [Parameter("Model", DefaultValue = SignalModel.Sonnet55)]
        public SignalModel Model { get; set; }

        [Parameter("Timeframe 1")]
        public TimeFrame TimeframeOne { get; set; }

        [Parameter("Timeframe 2")]
        public TimeFrame TimeframeTwo { get; set; }

        [Parameter("Timeframe 3")]
        public TimeFrame TimeframeThree { get; set; }
    }
}
