/* Speaking to the assistant, and hearing it answer.
 *
 * Entirely in the browser. The Web Speech API does both halves - recognition
 * and synthesis - so no audio leaves the machine, there is no provider to pay
 * and no key to leak. Groq serves Whisper on the same key the rest of this
 * uses, and it is the better transcriber; it is not worth uploading a
 * student's voice to find that out.
 *
 * Support is uneven and that is designed for rather than assumed: neither
 * control is rendered unless its API exists, so a browser without them shows
 * the page it always showed rather than a button that does nothing.
 */
(function () {
  'use strict';

  var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  var synth = window.speechSynthesis;

  // ---- Dictation -----------------------------------------------------

  function setUpDictation() {
    var field = document.getElementById('id_question');
    var slot = document.getElementById('voice-input-slot');
    if (!Recognition || !field || !slot) { return; }

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-outline-secondary';
    button.title = 'Ask by speaking';
    button.setAttribute('aria-label', 'Ask by speaking');
    button.innerHTML = '<i class="fas fa-microphone"></i>';
    slot.appendChild(button);

    var recognition = new Recognition();
    recognition.lang = document.documentElement.lang || 'en-IN';
    recognition.interimResults = true;
    // One question at a time. Continuous mode keeps the microphone open after
    // the person has stopped talking, which is both a privacy surprise and a
    // way to capture the next thing said in the room.
    recognition.continuous = false;

    var listening = false;

    function paint() {
      button.classList.toggle('btn-danger', listening);
      button.classList.toggle('btn-outline-secondary', !listening);
      button.title = listening ? 'Stop listening' : 'Ask by speaking';
    }

    button.addEventListener('click', function () {
      if (listening) { recognition.stop(); return; }
      try {
        recognition.start();
      } catch (err) {
        // start() throws if it is already running - harmless, and better than
        // an unhandled error in the console during a demo.
      }
    });

    recognition.addEventListener('start', function () {
      listening = true;
      paint();
      field.placeholder = 'Listening...';
    });

    recognition.addEventListener('result', function (event) {
      var text = '';
      for (var i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      field.value = text.trim();
    });

    recognition.addEventListener('error', function (event) {
      listening = false;
      paint();
      // 'not-allowed' is the person declining the microphone, which is a
      // choice rather than a fault; say nothing and leave the box typable.
      field.placeholder = event.error === 'not-allowed'
        ? 'Microphone not allowed - type instead'
        : 'Ask about attendance, fees, leave, or your course material...';
    });

    recognition.addEventListener('end', function () {
      listening = false;
      paint();
      field.placeholder =
        'Ask about attendance, fees, leave, or your course material...';
      if (field.value.trim()) { field.focus(); }
    });
  }

  // ---- Reading an answer out loud ------------------------------------

  function setUpPlayback() {
    if (!synth) { return; }

    var speaking = null;

    Array.prototype.forEach.call(
      document.querySelectorAll('[data-speak]'), function (button) {
        button.hidden = false;

        button.addEventListener('click', function () {
          // A second click on the same answer stops it; on a different one it
          // switches, rather than reading two answers over each other.
          if (speaking === button) { synth.cancel(); return; }
          synth.cancel();

          var text = button.getAttribute('data-speak');
          var utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = document.documentElement.lang || 'en-IN';
          utterance.rate = 1;

          utterance.addEventListener('end', function () {
            speaking = null;
            paint(button, false);
          });

          speaking = button;
          paint(button, true);
          synth.speak(utterance);
        });
      });

    function paint(button, active) {
      button.innerHTML = active
        ? '<i class="fas fa-stop"></i> Stop'
        : '<i class="fas fa-volume-up"></i> Listen';
    }

    // A page left mid-sentence keeps talking in some browsers.
    window.addEventListener('beforeunload', function () { synth.cancel(); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setUpDictation();
    setUpPlayback();
  });
})();
