/**
 * Minimal Streamlit custom-component bridge (no npm/CDN dependency).
 * Implements the subset used by mc_picker: ready, render, value, frame height.
 */
(function () {
  var RENDER_EVENT = "streamlit:render";
  var lastFrameHeight = null;

  function sendBackMsg(type, data) {
    var payload = { isStreamlitMessage: true, type: type };
    for (var key in data) {
      if (Object.prototype.hasOwnProperty.call(data, key)) {
        payload[key] = data[key];
      }
    }
    window.parent.postMessage(payload, "*");
  }

  function onMessageEvent(event) {
    var data = event.data;
    if (!data || data.type !== RENDER_EVENT) {
      return;
    }
    var args = data.args || {};
    var detail = {
      disabled: Boolean(data.disabled),
      args: args,
      theme: data.theme || null,
    };
    window.Streamlit.events.dispatchEvent(
      new CustomEvent(RENDER_EVENT, { detail: detail })
    );
  }

  window.Streamlit = {
    API_VERSION: 1,
    RENDER_EVENT: RENDER_EVENT,
    events: new EventTarget(),
    registeredMessageListener: false,
    setComponentReady: function () {
      if (!window.Streamlit.registeredMessageListener) {
        window.addEventListener("message", onMessageEvent);
        window.Streamlit.registeredMessageListener = true;
      }
      sendBackMsg("streamlit:componentReady", { apiVersion: 1 });
    },
    setFrameHeight: function (height) {
      if (height === undefined) {
        height = document.body.scrollHeight;
      }
      if (height === lastFrameHeight) {
        return;
      }
      lastFrameHeight = height;
      sendBackMsg("streamlit:setFrameHeight", { height: height });
    },
    setComponentValue: function (value) {
      sendBackMsg("streamlit:setComponentValue", {
        value: value,
        dataType: "json",
      });
    },
  };
})();
