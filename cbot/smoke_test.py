import clr

clr.AddReference("cAlgo.API")
from cAlgo.API import *
from robot_wrapper import *
from System import Uri


class SmokeTest():
    def on_start(self):
        self.check()

    def on_bar_closed(self):
        self.check()

    def check(self):
        base = api.BackendUrl.rstrip("/")
        health = api.Http.Send(HttpRequest(Uri(base + "/health")))
        api.Print(f"GET /health -> {health.StatusCode} {health.Body}")
        request = HttpRequest(Uri(base + "/ingest"))
        request.Method = HttpMethod.Post
        request.Headers.Add("X-API-Key", api.ApiKey)
        request.Headers.Add("Content-Type", "application/json")
        request.Body = '{"ping": true}'
        reply = api.Http.Send(request)
        api.Print(f"POST /ingest -> {reply.StatusCode} {reply.Body}")
