const int numPads = 8;

const int piezoPins[numPads] = {
  A0, A1, A2, A3, A4, A5, A6, A7
};

const int midiNotes[numPads] = {
  36, 38, 42, 48, 45, 41, 49, 51
};

// Trigger thresholds, adjustable from Python
int hitThreshold[numPads] = {
  40, 40, 40, 40, 40, 40, 40, 40
};

int resetThreshold[numPads] = {
  20, 20, 20, 20, 20, 20, 20, 20
};

bool armed[numPads] = {
  true, true, true, true,
  true, true, true, true
};

const unsigned long peakTime = 10;

void setup() {
  Serial.begin(115200);
}

void readCommands() {

  if (!Serial.available()) {
    return;
  }

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (!cmd.startsWith("SET,")) {
    return;
  }

  int p1 = cmd.indexOf(',');
  int p2 = cmd.indexOf(',', p1 + 1);
  int p3 = cmd.indexOf(',', p2 + 1);

  if (p1 < 0 || p2 < 0 || p3 < 0) {
    return;
  }

  String setting = cmd.substring(p1 + 1, p2);
  int pad = cmd.substring(p2 + 1, p3).toInt();
  int value = cmd.substring(p3 + 1).toInt();

  if (pad < 0 || pad >= numPads) {
    return;
  }

  if (setting == "HIT") {
    hitThreshold[pad] = constrain(value, 0, 1023);
  }

  else if (setting == "RESET") {
    resetThreshold[pad] = constrain(value, 0, 1023);
  }
}

void loop() {

  // Process commands from Python
  readCommands();

  for (int pad = 0; pad < numPads; pad++) {

    int value = analogRead(piezoPins[pad]);

    // Re-arm after signal falls below reset threshold
    if (!armed[pad]) {

      if (value < resetThreshold[pad]) {
        armed[pad] = true;
      }

      continue;
    }

    // Trigger
    if (value >= hitThreshold[pad]) {

      int peak = value;

      unsigned long start = millis();

      // Capture the highest ADC value for 10 ms
      while (millis() - start < peakTime) {

        value = analogRead(piezoPins[pad]);

        if (value > peak) {
          peak = value;
        }

        // Still allow threshold commands to be received
        readCommands();
      }

      // Convert raw ADC peak (0-1023) to MIDI velocity (1-127)
      int velocity = map(
        peak,
        hitThreshold[pad],
        1023,
        1,
        127
      );

      velocity = constrain(velocity, 1, 127);

      // Send MIDI hit
      Serial.print("NOTE,");
      Serial.print(midiNotes[pad]);
      Serial.print(",");
      Serial.println(velocity);

      // Send actual raw ADC peak
      Serial.print("RAW,");
      Serial.print(pad);
      Serial.print(",");
      Serial.println(peak);

      // Lock this pad until signal drops
      armed[pad] = false;
    }
  }
}
