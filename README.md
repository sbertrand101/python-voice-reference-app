<div align="center">

# Python Voice Reference App

<a href="http://dev.bandwidth.com"><img src="https://s3.amazonaws.com/bwdemos/BW_Voice.png"/></a>
</div>

This application demonstrates how to implement voice calling for mobile
devices, browsers (WebRTC), and any SIP client using the Bandwidth Application
Platform. This reference application makes creating, registering, and
implementing voice calling for endpoints (mobile, web, or any SIP client)
easy. This application implements the steps documented 
[here](http://ap.bandwidth.com/docs/how-to-guides/use-endpoints-make-receive-calls-sip-clients/).

You can open up the web page at the root of the deployed project for more 
instructions and for example of voice calling in your web browser using WebRTC.
Current browser supported: Chrome and Opera.

## Install
Before running, copy src/config.py.example to src/config.py and edit it with
your configuration values.  The example config.py contains explanations of each
configuration option.

After that run `pip install -r requirements.txt` to install dependencies. (You
may wish to use `virtualenv` to prevent polluting your system python
installation). Example assumes linux:

```
virtualenv --python=python3 venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run locally with ngrok
Run your server locally and and expose it to the internet (even behind a
NAT or firewall) via [ngrok](https://ngrok.com/).

 * Follow the instructions from the installation section
 * Install [ngrok](https://ngrok.com/download)
 * Start an ngrok tunnel `ngrok http 5000`
 * Start the app `source venv/bin/activate && cd src && python app.py`
 * Visit the your ngrok url e.g. http://6199623a.ngrok.io

## Http routes

**GET /** hompage

**POST /users** with required json payload `{"userName": "", "password": "" }`
to register a user

**POST /users/{userName}/callback** with json payload to handle Catapult call
events
