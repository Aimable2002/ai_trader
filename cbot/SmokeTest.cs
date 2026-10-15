using cAlgo.API;

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
