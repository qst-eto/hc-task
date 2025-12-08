// ===== Arduino TTL Output =====
// Python 側から "PULSE\n" を受け取ると TTL パルスを出す
// PIN: 出力ピン番号
// PULSE_MS: パルス幅（ミリ秒）

const int PIN = 13;      // TTL 出力に使うピン (例: 13番、必要なら変更)
const int PULSE_MS = 5;  // パルス幅（ミリ秒）

void setup() {
  pinMode(PIN, OUTPUT);
  digitalWrite(PIN, LOW);   // 初期状態は Low
  Serial.begin(115200);     // Python 側とボーレートを合わせる
}

void loop() {
  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');  // 改行まで読み込み
    s.trim();  // 前後の空白削除
    if (s == "PULSE") {
      digitalWrite(PIN, HIGH);   // TTL High
      delay(PULSE_MS);
      digitalWrite(PIN, LOW);    // 戻す
    }
  }
}
