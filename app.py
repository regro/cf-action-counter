import datetime
import pytz
import dateutil.parser
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
import requests

import cachetools
from flask import (
    Flask, request, make_response, jsonify, render_template)

APP_DATA = {
    'azure-pipelines': {
        'repos': cachetools.LRUCache(maxsize=128),
        'rates': cachetools.LRUCache(maxsize=96),
    },
    'travis-ci': {
        'repos': cachetools.LRUCache(maxsize=128),
        'rates': cachetools.LRUCache(maxsize=96),
    },
    'github-actions': {
        'repos': cachetools.LRUCache(maxsize=128),
        'rates': cachetools.LRUCache(maxsize=96),
    }
}

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

    global APP_DATA

    data = requests.get(
        ("https://raw.githubusercontent.com/regro/cf-action-counter-db/"
         "master/data/latest.json")).json()

    for slug in APP_DATA:
        print('reloading data for %s' % slug)

        if slug not in data:
            if slug != 'github-actions':
                continue
            else:
                _data = data
        else:
            _data = data[slug]

        for repo in _data['repos']:
            APP_DATA[slug]['repos'][repo] = _data['repos'][repo]

        for ts in _data['rates']:
            t = datetime.datetime.fromisoformat(ts).astimezone(pytz.UTC)
            key = _make_time_key(t)
            APP_DATA[slug]['rates'][key] = _data['rates'][ts]

        print("    reloaded %d repos" % len(APP_DATA[slug]['repos']))
        print("    reloaded %d rates" % len(APP_DATA[slug]['rates']))
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

    report = {}
    for key in APP_DATA:
        rates = {}
        for k in range(know, know-96, -1):
            tstr = _make_est_from_time_key(k, iso=iso)
            rates[tstr] = APP_DATA[key]['rates'].get(k, 0)

        total = sum(v for v in rates.values())

        report[key] = {
            'total': total,
            'rates': rates,
            'repos': {k: v for k, v in APP_DATA[key]['repos'].items()},
        }

    return report


@app.route('/', methods=['GET'])
def index():
    yaml = MyYAML()
    return render_template(
        'index.html',
        report=yaml.dump(_make_report_data(iso=False)),
    )


@app.route('/report', methods=['GET'])
def report(name):
    data = _make_report_data(iso=True)
    resp = make_response(jsonify(data))
    resp.headers['Access-Control-Allow-Origin'] = "*"
    return resp


@app.route('/report/<name>', methods=['GET'])
def report_name(name):
    data = _make_report_data(iso=True)
    resp = make_response(jsonify(data[name]))
    resp.headers['Access-Control-Allow-Origin'] = "*"
    return resp


@app.route('/payload', methods=['POST'])
def payload():
    global APP_DATA

    if request.method == 'POST':
        event_type = request.headers.get('X-GitHub-Event')
        print(" ")
        print("event:", event_type)

        if event_type == 'ping':
            return 'pong'
        elif event_type == 'check_run':
            repo = request.json['repository']['full_name']
            cs = request.json['check_run']

            print("    repo:", repo)
            print("    app:", cs['app']['slug'])
            print("    action:", request.json['action'])
            print("    status:", cs['status'])
            print("    conclusion:", cs['conclusion'])

            if (
                cs['app']['slug'] in APP_DATA and
                cs['status'] == 'completed'
            ):
                print("    completed_at:", cs['completed_at'])
                key = cs['app']['slug']

                uptime = dateutil.parser.isoparse(cs['completed_at'])
                interval = _make_time_key(uptime)
                if interval not in APP_DATA[key]['rates']:
                    APP_DATA[key]['rates'][interval] = 0
                APP_DATA[key]['rates'][interval] = (
                    APP_DATA[key]['rates'][interval]
                    + 1
                )

                if repo not in APP_DATA[key]['repos']:
                    APP_DATA[key]['repos'][repo] = 0
                APP_DATA[key]['repos'][repo] = (
                    APP_DATA[key]['repos'][repo]
                    + 1
                )

            return event_type
        elif event_type == 'check_suite':
            return event_type
        else:
            return make_response(
                "could not handle event: '%s'" % event_type,
                404,
            )
