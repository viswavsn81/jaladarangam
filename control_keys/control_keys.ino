// Reads the three ADC2-replacement control-key FSRs (gamakam, octave+,
// octave-) on A0/A1/A2 and prints them as CSV each cycle, for
// jaladarangam.py to parse over serial: "gamakam,octave_up,octave_down\n".
// A4/A5 are intentionally unused - reserved for this board's I2C bus.
// This supersedes a0_raw_test.ino (single-channel bring-up test) now that
// all three channels are wired and validated individually.
void setup() {
  Serial.begin(115200);
}

void loop() {
  int gamakam = analogRead(A0);
  int octave_up = analogRead(A1);
  int octave_down = analogRead(A2);
  Serial.print(gamakam);
  Serial.print(',');
  Serial.print(octave_up);
  Serial.print(',');
  Serial.println(octave_down);
  delay(20);
}
