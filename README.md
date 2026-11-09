# Nose Pointer

[English](#english) · [Русский](#русский)

Hands-free cursor control for Windows with a webcam. Move your nose to steer the pointer, click by winking or holding the pointer still, or use movement alone with a separate input device.

**[Download the Windows ZIP (v0.9.7)](https://github.com/orangepony4/nose-pointer/archive/refs/tags/v0.9.7.zip)** · [Release notes](https://github.com/orangepony4/nose-pointer/releases/tag/v0.9.7)

## English

### Install on Windows

You need Windows 10 or 11 (x64), a webcam, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Extract the ZIP and double-click **Start Nose Pointer.cmd**. The first run needs internet access to set up Python 3.12, the pinned dependencies, and the MediaPipe model. The launcher verifies the model with SHA-256. Camera tracking runs locally after setup.

To install and launch from PowerShell, run these commands in the extracted folder.

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
4. Tap **F8** in Nose Pointer to pause. In another window, hold **F8** briefly. You can also press **Esc** in Nose Pointer, select **Pause** (Пауза), or close the app. **Turn off camera** (Выключить камеру) stops capture.

If the default camera fails to open or points at the wrong device, turn it off if needed, change **Camera number** to `1` or another number, and select **Open camera** again. The number applies to the current session.

When you open the camera, the app tries Media Foundation for the same camera number if DirectShow cannot open it or deliver its first frame. Once video arrives, the app keeps using that backend for that capture session.

On shorter windows, scroll the practice area and settings above the camera and mouse buttons. Use **Page Up** or **Page Down** to scroll with the keyboard. Pressing **Tab** brings each focused control into view. If control stops for safety or an error occurs, a brief reason stays near the buttons while you scroll.

### Choose how to click

Use **Click mode** (Режим клика) in practice mode.

- **Wink** (Подмигивание). Wink with the left or right eye and reopen it to send the corresponding click. The pointer holds still during the wink. Blinking both eyes and closing one eye for too short or too long a time produce no click.
- **Dwell** (Задержка курсора). Move to a target and hold the pointer there. The progress bar tracks the delay, which defaults to 1.2 seconds and can be set from 0.6 to 5 seconds. Move away before the next click. For one right click, select **Right click** (Правый клик), then move to the target and dwell. You can select that button with a regular dwell click when system control is enabled. The next dwell returns to left-click behavior. Select **Cancel** (Отменить) to clear the choice.
- **Motion only** (Только движение). Use nose movement for the pointer and another device for clicks. This mode uses face position for calibration and steering.

### Recalibrate and recover

With system control enabled, tap **F9** in Nose Pointer to recalibrate from the current cursor position. In another window, hold **F9** briefly. In practice mode, use **Sensitivity** (Чувствительность) to tune the amount of head movement. **High** (Высокая) needs less movement, and **Low** (Низкая) gives finer control. Changing sensitivity starts a fresh calibration.

If you adjust your pose during desktop calibration, keep your final pose briefly as calibration finishes. The current cursor position is the starting point for your next movement.

A short loss of tracking pauses input. Keep your face in view and, in the click modes, open both eyes to resume. If another device moved the cursor during the pause, the app recalibrates at that location. After five seconds without an accepted face frame, Nose Pointer returns to practice mode and requires explicit re-enabling. The app also disables system input when it detects multiple faces or an abrupt face jump. Keep one person in view. Tracking loss or a pause clears dwell progress and any pending right click.

Enabling mouse control requires a recent preview frame. If the camera feed is delayed, wait for calibration in practice mode and select **Enable mouse** again.

If Windows reports an unexpected cursor position or a held physical mouse button as the app is about to click, Nose Pointer cancels the click and returns to practice mode. For a dwell click, the app makes these checks before moving the pointer and again before sending the click.

### Advanced settings

```powershell
uv run --locked nose_pointer.py --camera 1 --range-x 0.09 --range-y 0.08 --wink-ms 300
```

- `--camera 1` sets the initial **Camera number**. The default is `0`.
- `--range-x` and `--range-y` set the fraction of the frame you move from the neutral pose to reach a screen edge. Smaller values increase sensitivity. A custom pair appears as **Custom** (Своя) in the sensitivity menu.
- `--wink-ms` sets the minimum wink duration. The default is 220 ms.
- `--dwell-ms 1600` starts in dwell mode. The supported range is 600–5000 ms.
- `--no-mirror` reverses the horizontal mapping. `--swap-buttons` swaps the left and right wink actions. `--no-clicks` starts and locks the app in motion-only mode.
- `--lang ru` or `--lang en` overrides the saved language for that launch.

### Privacy and testing

Nose Pointer uses Python, Tkinter, OpenCV, [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python), and Windows input APIs. Camera frames stay in memory on your computer for local processing. This is an early prototype. Recognition depends on your camera, lighting, and range of motion, so try the practice area before enabling system control.

After setup, these commands check the app while the webcam stays off.

```powershell
uv run --locked python -m unittest discover -s tests -v
uv run --locked nose_pointer.py --check
```

The tests use synthetic face samples and mocked system input. The model check processes a blank image with the local model. See the [MIT license](LICENSE).

## Русский

[К английской версии](#english)

Nose Pointer управляет указателем Windows через веб-камеру. Движения носом перемещают указатель. Клик можно выполнить подмигиванием или задержкой на цели. Режим **Только движение** подходит, если для кликов удобнее другое устройство.

**[Скачать ZIP для Windows (v0.9.7)](https://github.com/orangepony4/nose-pointer/archive/refs/tags/v0.9.7.zip)** · [Описание релиза](https://github.com/orangepony4/nose-pointer/releases/tag/v0.9.7)

### Запуск на Windows

Нужны 64-битная Windows 10 или 11 (x64), веб-камера и [uv](https://docs.astral.sh/uv/getting-started/installation/). Распакуйте архив и откройте **Start Nose Pointer.cmd**. Для первого запуска нужен интернет. Программа установит Python 3.12 и зафиксированные зависимости, скачает модель MediaPipe и проверит её SHA-256. После настройки распознавание работает локально.

Для запуска из PowerShell выполните эти команды в распакованной папке.

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
4. Для паузы нажмите **F8** в окне Nose Pointer. В другом окне ненадолго удерживайте **F8**. Также можно нажать **Esc** в приложении, выбрать **Паузу** или закрыть окно. Кнопка **Выключить камеру** останавливает захват.

Если камера не открывается или выбрано другое устройство, выключите камеру при необходимости, измените **Номер камеры** на `1` или другой номер и снова нажмите **Открыть камеру**. Номер действует до закрытия приложения.

При открытии камеры приложение пробует Media Foundation для того же номера, если DirectShow не может открыть камеру или получить первый кадр. После получения видео приложение продолжает использовать выбранный способ захвата до выключения камеры.

В невысоком окне прокручивайте тестовое поле и настройки над кнопками камеры и мыши. Для прокрутки с клавиатуры нажмите **Page Up** или **Page Down**. При нажатии **Tab** элемент в фокусе появится в видимой части окна. Если управление остановилось для безопасности или произошла ошибка, краткая причина остаётся рядом с кнопками при прокрутке.

### Режимы клика

Выберите **Режим клика** в режиме пробы.

- **Подмигивание.** Подмигните левым или правым глазом и откройте его, чтобы выполнить соответствующий клик. Указатель удерживается на месте во время жеста. Моргание двумя глазами, слишком короткое или слишком долгое подмигивание не вызывают клик.
- **Задержка курсора.** Подведите указатель к цели и задержитесь. Полоса показывает ход отсчёта. По умолчанию задержка составляет 1,2 секунды, доступный диапазон от 0,6 до 5 секунд. Для следующего клика сначала отведите указатель. Для разового правого клика нажмите **Правый клик**, затем переместите указатель к цели и снова задержитесь. При включённой мыши эту кнопку можно нажать обычным кликом по задержке. После правого клика задержка снова даёт левый клик. Кнопка **Отменить** сбрасывает выбор.
- **Только движение.** Двигайте указатель носом и используйте другое устройство для кликов. Положение век не влияет на калибровку или движение в этом режиме.

### Калибровка и восстановление управления

При включённой мыши нажмите **F9** в окне Nose Pointer, чтобы заново откалибровать управление с текущей позиции указателя. В другом окне ненадолго удерживайте **F9**. В режиме пробы настройте **Чувствительность**. **Высокая** требует меньших движений головы, а **Низкая** помогает точнее наводить указатель. Смена чувствительности запускает калибровку заново.

Если сменили позу при калибровке системной мыши, ненадолго задержитесь в новой позе до завершения калибровки. Следующее движение начнётся с текущей позиции указателя.

При краткой потере отслеживания ввод приостанавливается. Верните лицо в кадр и откройте оба глаза, если используете режим клика. Если за время паузы указатель переместили другим устройством, программа откалибруется на новом месте. Через пять секунд без принятого кадра с лицом приложение возвращается в режим пробы. Для возобновления системного ввода снова нажмите **Включить мышь**. Программа также отключает ввод при нескольких лицах в кадре или резком смещении лица. Оставляйте в кадре одного человека. Потеря отслеживания или пауза отменяет отсчёт задержки и выбранный правый клик.

Для включения мыши нужен свежий кадр из режима пробы. Если кадры задержались, дождитесь калибровки и снова нажмите **Включить мышь**.

Если перед кликом Windows сообщает, что указатель оказался в другой точке или удерживается физическая кнопка мыши, Nose Pointer отменяет клик и возвращается в режим пробы. При клике по задержке приложение выполняет эти проверки перед перемещением указателя и ещё раз перед самим кликом.

### Дополнительные настройки

```powershell
uv run --locked nose_pointer.py --camera 1 --range-x 0.09 --range-y 0.08 --wink-ms 300
```

- `--camera 1` задаёт начальный **Номер камеры**. По умолчанию используется `0`.
- `--range-x` и `--range-y` задают долю кадра, которую нужно пройти от нейтральной позиции до края экрана. Меньшие значения повышают чувствительность. Своя пара значений появится в списке **Чувствительность** как **Своя**.
- `--wink-ms` задаёт минимальную длительность подмигивания. По умолчанию это 220 мс.
- `--dwell-ms 1600` открывает режим задержки и задаёт время ожидания от 600 до 5000 мс.
- `--no-mirror` меняет горизонтальное направление. `--swap-buttons` меняет местами левый и правый клики подмигиванием. `--no-clicks` запускает приложение в режиме **Только движение** и блокирует выбор других режимов.
- `--lang ru` или `--lang en` переопределяет сохранённый язык для этого запуска.

### Приватность и проверки

Приложение использует Python, Tkinter, OpenCV, [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python) и системный ввод Windows. Кадры обрабатываются локально и остаются в оперативной памяти компьютера. Это ранний прототип. На распознавание влияют камера, освещение и доступная амплитуда движений, поэтому сначала попробуйте управление в тестовом поле.

После установки эти команды проверяют работу приложения при выключенной камере.

```powershell
uv run --locked python -m unittest discover -s tests -v
uv run --locked nose_pointer.py --check
```

В тестах используются синтетические данные о лице и заглушки системного ввода. Проверка модели обрабатывает пустое изображение с локальной моделью. См. [лицензию MIT](LICENSE).
