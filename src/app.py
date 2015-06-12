import json
import pickle
from datetime import datetime
from random import choice
from string import ascii_letters
from os.path import exists
from flask import Flask, render_template, request, url_for, redirect, abort
from werkzeug.contrib.cache import SimpleCache
from bandwidth_sdk import Client, Application, PhoneNumber, Event, \
    IncomingCallEvent, HangupCallEvent, Domain, Endpoint, BaseResource,\
    Call, Bridge
from flask.json import JSONEncoder

app = Flask(__name__)
app.config.from_object('config')

# SimpleCache for application state. Only meant for use with the development
# server as SimpleCache is not 100% thread safe. Use a real cache or database
# for production apps. The cache is pickled and written to a file on disk so
# that users can be used across process restarts.
cache = None

# Domain for user endpoints.  Starts out uninitialized.  App will search to see
# if the domain has already been configured before attempting to create a new
# domain resource with catapult.
domain = None

# Initialize bandwidth sdk with your credentials
Client(app.config['CATAPULT_USER_ID'],
       app.config['CATAPULT_API_TOKEN'],
       app.config['CATAPULT_API_SECRET'])


def persist_cache():
    """Write the cache to disk so user configs survive restarts."""
    pickle.dump(cache, open('cache.p', 'wb'))


def load_cache():
    """Load cache from disk."""
    return pickle.load(open('cache.p', 'rb')) if exists('cache.p')\
        else SimpleCache(default_timeout=604800)  # 1 week timeout


def get_domain():
    """Fetch or create a catapult domain resource."""
    domain_name = app.config['DOMAIN']
    domains = [d for d in Domain.list(size=1000) if d.name == domain_name]
    if len(domains) > 0:
        return domains[0]
    else:
        return Domain.create(name=domain_name)


def pretty_encode(resource):
    """
    Encode app data in a pretty json format.  Useful when resources need to be
    presented to the user.
    :return json encoded string representation of <resource>
    """
    class PrettyEncoder(JSONEncoder):
        def default(self, o):
            if isinstance(o, datetime):
                return str(o)
            if isinstance(o, BaseResource):
                data = {}
                for field in o._fields:
                    value = getattr(o, field)
                    if not isinstance(value, BaseResource):
                        data[field] = value
                return data
            return super(PrettyEncoder, self).default(o)

    return json.dumps(resource, indent=3, cls=PrettyEncoder)


def get_user(user):
    """
    Get a user and config.  First attempts to pull a user from the cache.
    If no user is found in the cache then attempt to create a new user and all
    necessary catapult resources.

    :param user e.g. {'username': 'foo', 'password': 'bar'}.  user lookup will
    use the username key.
    :type dict
    """
    # first check to see if a user is in the cache
    username = user.get('username')
    if cache.get('user:%s' % username) is not None:
        return cache.get('user:%s' % username)

    # user is not in the cache, create
    application = Application.create(
        name=user.get('username'),
        incoming_call_url=url_for(
            'callback', username=username, _external=True),
        auto_answer=False)
    user['application_id'] = application.id

    phone_number = PhoneNumber.list_local(state='NC', quantity=1)[0]
    phone_number = phone_number.allocate(application=application.id)
    user['phone_number'] = phone_number.number
    user['phone_number_id'] = phone_number.id

    endpoint = domain.add_endpoint(
        name='uep-%s' % ''.join([choice(ascii_letters) for i in range(0, 12)]),
        description='Sandbox created Endpoint for user %s' % user['username'],
        application_id=application.id,
        enabled=True,
        credentials={'password': user['password']})
    user['endpoint_id'] = endpoint.id

    cache.set('user:%s' % user['username'], user)
    persist_cache()

    return user


@app.route('/')
def index():
    """Render the home page of the app"""
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    """Configures a new user or loads an existing user from the cache."""
    username = request.form.get('userName')
    if username is None or not username:
        return redirect(url_for('index'))

    user = get_user({
        'username': username,
        'password': ''.join([choice(ascii_letters) for i in range(0, 12)])
    })

    endpoint = Endpoint.get(domain.id, user['endpoint_id'])
    auth_token = endpoint.create_token()

    tpl_vars = {
        'username': user['username'],
        'authToken': auth_token.token,
        'authTokenDisplayData': pretty_encode(auth_token),
        'userData': pretty_encode(user['username']),
        'phoneNumber': user['phone_number'],
        'webrtcEnv': app.config['WEBRTC_ENV'],
        'domain': endpoint.credentials['realm']
    }

    return render_template('calldemo.html', **tpl_vars)


@app.route('/users/<username>/callback', methods=['POST'])
def callback(username=None):
    """
    Route a catapult callback to the appropriate handler.  These functions
    control call flow.
    :param username:
    :return:
    """
    user = cache.get('user:%s' % username)
    if user is None:
        app.logger.debug('received callback for unknown username=%s' % username)
        abort(403)

    # process the event
    event = Event.create(**request.json)
    app.logger.debug('received callback event: %s' % event)
    if isinstance(event, IncomingCallEvent):
        handle_incoming_call(event, user)
    elif isinstance(event, HangupCallEvent):
        handle_hangup(event)
    else:
        app.logger.debug('event unhandled: %s' % event)

    return 'ok'


def handle_incoming_call(event, user):
    """
    Handles an incoming call event.
    :param event:
    :param user:
    :return:
    """
    to_number = event.to
    from_number = event.from_

    if user.get('phone_number') == event.to:
        to_number = Endpoint.get(domain.id, user['endpoint_id']).sip_uri
    else:
        from_number = user.get('phone_number')

    # If it has a tag, it's the answer for the outbound call leg to the
    # user's endpoint
    if event.tag is not None:
        return

    call = Call.get(event.call_id)
    call.set_call_property(state=Call.STATES.active)
    call.play_audio(
        url_for('static', filename='sounds/ring.mp3', _external=True),
        loop_enabled=True)

    bridge = Bridge.create(call, bridge_audio=True)
    cache.set('call_bridge:%s' % event.call_id, bridge.id)

    # Create the outbound leg of the call to the user's endpoint
    # Include the bridgeId in this call
    url = url_for('callback', username=user.get('username'), _external=True)
    new_call = Call.create(from_number, to_number, bridge_id=bridge.id,
                           tag=call.call_id, callback_url=url)

    cache.set('call_bridge:%s' % new_call.call_id, bridge.id, timeout=86400)


def handle_hangup(event):
    """
    Handles hanging up all legs of a call.
    :param event:
    :return:
    """
    bridge_id = cache.get('call_bridge:%s' % event.call_id)
    if bridge_id:
        # call was not on a bridge no action is needed
        app.logger.debug('no cached bridge for call_id=%s' % event.call_id)
        return

    # Delete all active calls in bridge
    calls = Bridge.get(bridge_id).calls
    calls = [c for c in calls if not c.state == Call.STATES.active]
    for call in calls:
        app.logger.debug('hanging up call=%s' % call)
        Call.get(call.id).hangup()
        cache.delete('call_bridge:%s' % call.call_id)


if __name__ == '__main__':
    cache = load_cache()
    domain = get_domain()
    app.run(threaded=True, port=app.config['PORT'])
