import datetime
import pytz
import dateutil.parser
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
import requests

import cachetools
from flask import Flask, request, jsonify, render_template, make_response

REPOS = cachetools.LRUCache(maxsize=128)
RATES = cachetools.LRUCache(maxsize=96)

START_TIME = datetime.datetime.fromisoformat("2020-01-01T00:00:00+00:00")
TIME_INTERVAL = 60*5  # five minutes

app = Flask(__name__)


def _make_time_key(uptime):
    dt = uptime.timestamp() - START_TIME.timestamp()
    return int(dt // TIME_INTERVAL)


# reload the cache
RELOAD_CACHE = True


def _reload_cache():
    print(" ")
    print("!!!!!!!!!!!!!! RELOADING THE CACHE !!!!!!!!!!!!!!")

    global REPOS
    global RATES
    global RELOAD_CACHE

    data = requests.get(
        ("https://raw.githubusercontent.com/regro/cf-action-counter-db/"
         "master/data/latest.json")).json()
    for repo in data['repos']:
        REPOS[repo] = data['repos'][repo]

    for ts in data['rates']:
        t = datetime.datetime.fromisoformat(ts).astimezone(pytz.UTC)
        key = _make_time_key(t)
        RATES[key] = data['rates'][ts]

    print("reloaded %d repos" % len(REPOS))
    print("reloaded %d rates" % len(RATES))
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print(" ")


if RELOAD_CACHE:
    _reload_cache()
    RELOAD_CACHE = False


class MyYAML(YAML):
    """dump yaml as string rippd from docs"""
    def dump(self, data, stream=None, **kw):
        inefficient = False
        if stream is None:
            inefficient = True
            stream = StringIO()
        YAML.dump(self, data, stream, **kw)
        if inefficient:
            return stream.getvalue()


def _make_est_from_time_key(key, iso=False):
    est = pytz.timezone('US/Eastern')
    fmt = '%Y-%m-%d %H:%M:%S %Z%z'
    dt = datetime.timedelta(seconds=key * TIME_INTERVAL)
    t = dt + START_TIME
    t = t.astimezone(est)
    if iso:
        return t.isoformat()
    else:
        return t.strftime(fmt)


def _make_report_data(iso=False):
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    know = _make_time_key(now)

    rates = {}
    for k in range(know, know-96, -1):
        tstr = _make_est_from_time_key(k, iso=iso)
        rates[tstr] = RATES.get(k, 0)

    total = sum(v for v in rates.values())

    return {
        'total': total,
        'rates': rates,
        'repos': {k: v for k, v in REPOS.items()},
    }


@app.route('/')
def index():
    yaml = MyYAML()
    return render_template(
        'index.html',
        report=yaml.dump(_make_report_data(iso=False)),
    )


@app.route('/report')
def report():
    return jsonify(_make_report_data(iso=True))


@app.route('/payload', methods=['POST'])
def payload():
    global REPOS
    global RATES

    if request.method == 'POST':
        event_type = request.headers.get('X-GitHub-Event')
        print(" ")
        print("event:", event_type)

        if event_type == 'ping':
            return 'pong'
        elif event_type == 'check_suite':
            repo = request.json['repository']['full_name']
            cs = request.json['check_suite']

            print("    repo:", repo)
            print("    app:", cs['app']['slug'])
            print("    action:", request.json['action'])
            print("    status:", cs['status'])
            print("    conclusion:", cs['conclusion'])
            print("    updated_at:", cs['updated_at'])

            if cs['app']['slug'] == 'github-actions':
                uptime = dateutil.parser.isoparse(cs['updated_at'])
                interval = _make_time_key(uptime)

                if interval not in RATES:
                    RATES[interval] = 0
                RATES[interval] = RATES[interval] + 1

                if repo not in REPOS:
                    REPOS[repo] = 0
                REPOS[repo] = REPOS[repo] + 1

            return event_type
        else:
            return make_response(
                "could not handle event: '%s'" % event_type,
                404,
            )
