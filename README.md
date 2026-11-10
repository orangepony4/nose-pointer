# Nose Pointer

[English](#english) · [Русский](#русский)

Hands-free cursor control for Windows with a webcam. Move your nose to steer the pointer, click by winking or holding the pointer still, or use movement alone with a separate input device.

**[Download the Windows ZIP (v0.10.3)](https://github.com/orangepony4/nose-pointer/archive/refs/tags/v0.10.3.zip)** · [Release notes](https://github.com/orangepony4/nose-pointer/releases/tag/v0.10.3)

## English

### Install on Windows

You need Windows 10 or 11 (x64) and a webcam. Extract the ZIP to a writable folder and double-click **Start Nose Pointer.cmd**. On the first run, the launcher uses uv from PATH or downloads a verified copy from [Astral's releases](https://github.com/astral-sh/uv/releases/tag/0.13.1) into `.uv-bootstrap` inside the extracted folder. It then sets up Python 3.12 and the pinned dependencies and verifies the downloaded MediaPipe model. Setup needs internet access. Camera tracking runs locally after setup.

If you already have [uv](https://docs.astral.sh/uv/getting-started/installation/) on PATH, you can also run these commands from the extracted folder in PowerShell.

```powershell
uv sync --locked --python 3.12
uv run --locked nose_pointer.py --download-model
uv run --locked nose_pointer.py
```

### Start in practice mode

Nose Pointer opens in English on first launch. Use **Language** to switch to **Русский** before enabling system control or while in practice mode. Switching keeps your practice position and settings. The app saves the language preference in `%LOCALAPPDATA%\NosePointer\language.txt`.

The app remembers the sensitivity preset, click mode and dwell delay you choose. Each launch still starts with the camera and system control off. The command-line options `--range-x`, `--range-y`, `--no-clicks` and `--dwell-ms` override saved choices for that launch.

1. Select **Open camera** (Открыть камеру). The green dot is a practice pointer. Your Windows cursor stays under your usual control.
2. Look straight ahead while the app calibrates. The status shows calibration progress. Keep both eyes open in the click modes. Try moving the dot, then hold a wink for about a quarter of a second and open the eye. The app shows the recognized click below the practice area.
3. Choose your click mode and sensitivity while still in practice mode. Select **Enable mouse** (Включить мышь) when ready. Calibration uses the current cursor position as its starting point, and the pointer can reach across multiple monitors.
4. Tap **F8** in Nose Pointer to pause. In another window, hold **F8** briefly. The app checks **F8** again just before moving or clicking. You can also press **Esc** in Nose Pointer, select **Pause** (Пауза), or close the app. **Turn off camera** (Выключить камеру) stops capture.

If the default camera fails to open or points at the wrong device, turn it off if needed, change **Camera number** to `1` or another number, and select **Open camera** again. After the new camera calibrates in practice mode, Nose Pointer remembers its number for the next launch. The camera starts off each time.

When you open the camera, the app tries Media Foundation for the same camera number if DirectShow cannot open or configure the device or deliver its first frame. Once video arrives, the app keeps using that backend for that capture session.

On shorter windows, scroll the practice area and settings above the camera and mouse buttons. With large text, button captions may be shorter and the privacy note can move into the scrollable area. Use **Page Up** or **Page Down** to scroll with the keyboard. Pressing **Tab** brings each focused control into view. Use **Enter** or **Space** on the focused camera, mouse control or right-click button. The action runs once when you release the key while the same button has focus. If you switch windows with the key held, release it and press it again. If control stops for safety or an error occurs, a brief reason stays near the buttons while you scroll.

### Choose how to click

Use **Click mode** (Режим клика) in practice mode.

- **Wink** (Подмигивание). Wink with the left or right eye and reopen it to send the corresponding click. The pointer holds still during the wink. Blinking both eyes and closing one eye for too short or too long a time produce no click. If the eye stays partly open during the gesture, Nose Pointer measures the closure only up to the start of that reopening.
- **Dwell** (Задержка курсора). Move to a target and hold the pointer there. The progress bar tracks the delay, which defaults to 1.2 seconds and can be set from 0.6 to 5 seconds. A clear closure of either eye restarts the timer. Move the visible cursor away before the next click. If the cursor reaches a gap between displays, the timer follows its visible position on the display edge. For one right click, select **Right click** (Правый клик), then move to the target and dwell. You can select that button with a regular dwell click when system control is enabled. The next dwell returns to left-click behavior. Select **Cancel** (Отменить) to clear the choice.
- **Motion only** (Только движение). Use nose movement for the pointer and another device for clicks. This mode uses face position for calibration and steering.

### Recalibrate and recover

With system control enabled, tap **F9** in Nose Pointer to recalibrate from the current cursor position. In another window, hold **F9** briefly. In practice mode, use **Sensitivity** (Чувствительность) to tune the amount of head movement. **High** (Высокая) needs less movement, and **Low** (Низкая) gives finer control. Changing sensitivity starts a fresh calibration.

When you enable mouse control or request recalibration, the app uses camera frames captured from that moment onward. If you adjust your pose during desktop calibration, keep your final pose briefly as calibration finishes. The current cursor position is the starting point for your next movement.

A short loss of tracking pauses input. Keep your face in view and, in the click modes, open both eyes to resume. If another device moved the cursor during the pause, the app recalibrates at that location. After five seconds without an accepted face frame, Nose Pointer returns to practice mode and requires explicit re-enabling. The app also returns to practice if it sees multiple faces, an abrupt jump, or a face reappearing far from its last position. An abrupt jump can stop control even if the face returns to its previous position before the interface refreshes. Keep one person in view. Tracking loss or a pause clears dwell progress and any pending right click.

Enabling mouse control requires a recent preview frame. If the camera feed is delayed, wait for calibration in practice mode and select **Enable mouse** again.

In one Windows session, one Nose Pointer window controls the mouse at a time. Other windows can stay in practice. Pause the active window, stop its camera, or close it before enabling control in another one.

If Windows reports an unexpected cursor position or a held physical mouse button, including a side button, as the app is about to click, Nose Pointer cancels the click and returns to practice mode. For a dwell click, the app makes these checks before moving the pointer and again before sending the click.

If you connect, disconnect, or rearrange a display, Nose Pointer returns to practice mode before sending more input. After calibration, select **Enable mouse** to use the new display layout.

### Advanced settings

```powershell
uv run --locked nose_pointer.py --camera 1 --range-x 0.09 --range-y 0.08 --wink-ms 300
```

- `--camera 1` overrides the initial **Camera number** for this launch. Otherwise the app uses the saved number, or `0` on first launch.
- `--range-x` and `--range-y` set the fraction of the frame you move from the neutral pose to reach a screen edge. Smaller values increase sensitivity. A custom pair appears as **Custom** (Своя) in the sensitivity menu.
- `--wink-ms` sets the minimum wink duration. The default is 220 ms.
- `--dwell-ms 1600` starts in dwell mode. The supported range is 600–5000 ms.
- `--no-mirror` reverses the horizontal mapping. `--swap-buttons` swaps the left and right wink actions. `--no-clicks` starts and locks the app in motion-only mode.
- `--lang ru` or `--lang en` overrides the saved language for that launch.

### Privacy and testing

Nose Pointer uses Python, Tkinter, OpenCV, [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python), and Windows input APIs. Camera frames stay in memory on your computer for local processing. This is an early prototype. Recognition depends on your camera, lighting, and range of motion, so try the practice area before enabling system control.

To verify your installation with the webcam off, open PowerShell in the extracted folder and run the Windows launcher in check mode. The first run uses the same setup as double-clicking the launcher, so it needs internet access.

```powershell
& '.\Start Nose Pointer.cmd' --check --lang en
```

`--check` converts a blank frame with OpenCV and passes it to the same local model used for webcam frames. A successful check prints `Model check passed. The camera stayed off.`

If you already have uv on PATH, you can also run the unit tests. They use synthetic face samples and mocked system input.

```powershell
uv run --locked python -m unittest discover -s tests -v
```

See the [MIT license](LICENSE).

## Русский

[К английской версии](#english)

Nose Pointer управляет указателем Windows через веб-камеру. Движения носом перемещают указатель. Клик можно выполнить подмигиванием или задержкой на цели. Режим **Только движение** подходит, если для кликов удобнее другое устройство.

**[Скачать ZIP для Windows (v0.10.3)](https://github.com/orangepony4/nose-pointer/archive/refs/tags/v0.10.3.zip)** · [Описание релиза](https://github.com/orangepony4/nose-pointer/releases/tag/v0.10.3)

### Запуск на Windows

Нужны 64-битная Windows 10 или 11 (x64) и веб-камера. Распакуйте архив в папку с правом записи и откройте **Start Nose Pointer.cmd**. При первом запуске программа использует установленный uv или скачивает проверенную копию из [релизов Astral](https://github.com/astral-sh/uv/releases/tag/0.13.1) в папку `.uv-bootstrap` внутри распакованного архива. Затем программа настраивает Python 3.12 и зафиксированные зависимости и проверяет скачанную модель MediaPipe. Для настройки нужен интернет. После неё распознавание работает локально.

Если [uv](https://docs.astral.sh/uv/getting-started/installation/) уже доступен через PATH, можно выполнить эти команды из распакованной папки в PowerShell.

```powershell
uv sync --locked --python 3.12
uv run --locked nose_pointer.py --download-model
uv run --locked nose_pointer.py
```

### Первое использование

При первом запуске интерфейс открывается на английском. Выберите **Language → Русский** до включения системной мыши или в режиме пробы. Настройки и положение тестового указателя сохранятся. Язык запоминается в файле `%LOCALAPPDATA%\NosePointer\language.txt`.

Приложение запоминает выбранный профиль чувствительности, режим клика и задержку. При каждом запуске камера и системное управление выключены. Параметры командной строки `--range-x`, `--range-y`, `--no-clicks` и `--dwell-ms` имеют приоритет над сохранёнными настройками на время текущего запуска.

1. Нажмите **Открыть камеру**. В режиме пробы зелёная точка движется в окне, а курсор Windows остаётся под вашим обычным управлением.
2. Смотрите прямо во время калибровки. В строке состояния видно, сколько уже пройдено. В режимах клика держите оба глаза открытыми. Попробуйте подвигать точку, затем подмигните одним глазом примерно на четверть секунды и откройте его. Под тестовым полем появится сторона распознанного клика.
3. Подберите режим клика и чувствительность в режиме пробы. Нажмите **Включить мышь**, когда будете готовы. Текущая позиция указателя станет опорной точкой. Управление охватывает и дополнительные мониторы.
4. Для паузы нажмите **F8** в окне Nose Pointer. В другом окне ненадолго удерживайте **F8**. Приложение проверяет **F8** ещё раз перед движением или кликом. Также можно нажать **Esc** в приложении, выбрать **Паузу** или закрыть окно. Кнопка **Выключить камеру** останавливает захват.

Если камера не открывается или выбрано другое устройство, выключите камеру при необходимости, измените **Номер камеры** на `1` или другой номер и снова нажмите **Открыть камеру**. После калибровки в режиме пробы Nose Pointer запомнит новый номер. При каждом запуске камера выключена.

При открытии камеры приложение пробует Media Foundation для того же номера, если DirectShow не может открыть или настроить устройство либо получить первый кадр. После получения видео приложение продолжает использовать выбранный способ захвата до выключения камеры.

В невысоком окне прокручивайте тестовое поле и настройки над кнопками камеры и мыши. При крупном тексте подписи кнопок могут сокращаться, а пояснение об обработке кадров может переместиться в прокручиваемую область. Для прокрутки с клавиатуры нажмите **Page Up** или **Page Down**. При нажатии **Tab** элемент в фокусе появится в видимой части окна. Нажмите **Enter** или **Пробел**, когда в фокусе кнопка камеры, управления мышью или правого клика. Действие выполняется один раз при отпускании клавиши, пока та же кнопка остаётся в фокусе. Если вы переключили окно с зажатой клавишей, отпустите её и нажмите снова. Если управление остановилось для безопасности или произошла ошибка, краткая причина остаётся рядом с кнопками при прокрутке.

### Режимы клика

Выберите **Режим клика** в режиме пробы.

- **Подмигивание.** Подмигните левым или правым глазом и откройте его, чтобы выполнить соответствующий клик. Указатель удерживается на месте во время жеста. Моргание двумя глазами, слишком короткое или слишком долгое подмигивание не вызывают клик. Если глаз остаётся приоткрытым во время жеста, Nose Pointer измеряет длительность смыкания век до того момента, когда глаз начал открываться.
- **Задержка курсора.** Подведите указатель к цели и задержитесь. Полоса показывает ход отсчёта. По умолчанию задержка составляет 1,2 секунды, доступный диапазон от 0,6 до 5 секунд. Если любой из глаз закрывается, отсчёт начинается заново. Для следующего клика сначала отведите видимый указатель. Если указатель упирается в промежуток между экранами, отсчёт учитывает его видимое положение на краю экрана. Для разового правого клика нажмите **Правый клик**, затем переместите указатель к цели и снова задержитесь. При включённой мыши эту кнопку можно нажать обычным кликом по задержке. После правого клика задержка снова даёт левый клик. Кнопка **Отменить** сбрасывает выбор.
- **Только движение.** Двигайте указатель носом и используйте другое устройство для кликов. Положение век не влияет на калибровку или движение в этом режиме.

### Калибровка и восстановление управления

При включённой мыши нажмите **F9** в окне Nose Pointer, чтобы заново откалибровать управление с текущей позиции указателя. В другом окне ненадолго удерживайте **F9**. В режиме пробы настройте **Чувствительность**. **Высокая** требует меньших движений головы, а **Низкая** помогает точнее наводить указатель. Смена чувствительности запускает калибровку заново.

После включения управления мышью или запроса повторной калибровки приложение использует кадры, снятые с этого момента. Если сменили позу при калибровке системной мыши, ненадолго задержитесь в новой позе до её завершения. Следующее движение начнётся с текущей позиции указателя.

При краткой потере отслеживания ввод приостанавливается. Верните лицо в кадр и откройте оба глаза, если используете режим клика. Если за время паузы указатель переместили другим устройством, программа откалибруется на новом месте. Через пять секунд без принятого кадра с лицом приложение возвращается в режим пробы. Для возобновления системного ввода снова нажмите **Включить мышь**. Программа также возвращается в режим пробы, если видит несколько лиц, резкое смещение или лицо, которое снова появилось далеко от прежнего положения. Резкое смещение может отключить управление, даже если лицо уже вернулось на прежнее место к следующему обновлению интерфейса. Оставляйте в кадре одного человека. Потеря отслеживания или пауза отменяет отсчёт задержки и выбранный правый клик.

Для включения мыши нужен свежий кадр из режима пробы. Если кадры задержались, дождитесь калибровки и снова нажмите **Включить мышь**.

В одном сеансе Windows мышью управляет одно окно Nose Pointer. Остальные окна могут работать в режиме пробы. Поставьте активное окно на паузу, выключите в нём камеру или закройте его, затем включите управление в другом.

Если перед кликом Windows сообщает, что указатель оказался в другой точке или удерживается кнопка мыши, в том числе боковая, Nose Pointer отменяет клик и возвращается в режим пробы. При клике по задержке приложение выполняет эти проверки перед перемещением указателя и ещё раз перед самим кликом.

Если подключить, отключить или переставить экран, Nose Pointer возвращается в режим пробы перед следующим движением или кликом. После калибровки нажмите **Включить мышь**, чтобы работать с новой схемой экранов.

### Дополнительные настройки

```powershell
uv run --locked nose_pointer.py --camera 1 --range-x 0.09 --range-y 0.08 --wink-ms 300
```

- `--camera 1` задаёт начальный **Номер камеры** на один запуск. Без этого параметра приложение использует сохранённый номер, а при первом запуске выбирает `0`.
- `--range-x` и `--range-y` задают долю кадра, которую нужно пройти от нейтральной позиции до края экрана. Меньшие значения повышают чувствительность. Своя пара значений появится в списке **Чувствительность** как **Своя**.
- `--wink-ms` задаёт минимальную длительность подмигивания. По умолчанию это 220 мс.
- `--dwell-ms 1600` открывает режим задержки и задаёт время ожидания от 600 до 5000 мс.
- `--no-mirror` меняет горизонтальное направление. `--swap-buttons` меняет местами левый и правый клики подмигиванием. `--no-clicks` запускает приложение в режиме **Только движение** и блокирует выбор других режимов.
- `--lang ru` или `--lang en` переопределяет сохранённый язык для этого запуска.

### Приватность и проверки

Приложение использует Python, Tkinter, OpenCV, [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python) и системный ввод Windows. Кадры обрабатываются локально и остаются в оперативной памяти компьютера. Это ранний прототип. На распознавание влияют камера, освещение и доступная амплитуда движений, поэтому сначала попробуйте управление в тестовом поле.

Чтобы проверить установку с выключенной камерой, откройте PowerShell в распакованной папке и запустите программу в режиме проверки. При первом запуске выполняется та же установка, что и при двойном щелчке по файлу запуска, поэтому нужен интернет.

```powershell
& '.\Start Nose Pointer.cmd' --check --lang ru
```

`--check` преобразует пустой кадр с помощью OpenCV и передаёт его в ту же локальную модель, которая обрабатывает кадры веб-камеры. При успехе появится сообщение `Модель и обработка кадров работают. Камера оставалась выключенной.`

Если uv уже доступен в PATH, можно запустить тесты. Они используют синтетические данные о лице и заглушки системного ввода.

```powershell
uv run --locked python -m unittest discover -s tests -v
```

См. [лицензию MIT](LICENSE).
