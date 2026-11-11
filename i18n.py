"""English and Russian messages for the desktop app and launcher commands."""

from preferences import read_preference, save_preference

LANGUAGES = {"en": "English", "ru": "Русский"}

MESSAGES = {
    "subtitle": ("Webcam pointer control", "Управление указателем через веб-камеру"),
    "language": ("Language", "Язык"),
    "sensitivity": ("Sensitivity", "Чувствительность"),
    "sensitivity_low": ("Low", "Низкая"),
    "sensitivity_standard": ("Standard", "Обычная"),
    "sensitivity_high": ("High", "Высокая"),
    "sensitivity_custom": ("Custom", "Своя"),
    "click_mode": ("Click mode", "Режим клика"),
    "wink": ("Wink", "Подмигивание"),
    "dwell": ("Dwell", "Задержка курсора"),
    "motion": ("Motion only", "Только движение"),
    "dwell_delay": ("Delay (s)", "Задержка, с"),
    "dwell_eye": ("Eye for dwell", "Глаз для задержки"),
    "dwell_eye_both": ("Both eyes", "Оба глаза"),
    "dwell_eye_left": ("Left eye", "Левый глаз"),
    "dwell_eye_right": ("Right eye", "Правый глаз"),
    "open_camera": ("Open camera", "Открыть камеру"),
    "open_camera_short": ("Start camera", "Вкл. камеру"),
    "stop_camera": ("Turn off camera", "Выключить камеру"),
    "stop_camera_short": ("Stop camera", "Выкл. камеру"),
    "camera_index": ("Camera number", "Номер камеры"),
    "camera_index_invalid": ("Enter a whole camera number, such as 0 or 1.",
                             "Введите целый номер камеры, например 0 или 1."),
    "enable_mouse": ("Enable mouse", "Включить мышь"),
    "enable_mouse_short": ("Mouse on", "Вкл. мышь"),
    "pause": ("Pause", "Пауза"),
    "right_click": ("Right click", "Правый клик"),
    "cancel": ("Cancel", "Отменить"),
    "hotkeys": ("F8  ·  Pause     F9  ·  Recalibrate", "F8  ·  Пауза     F9  ·  Калибровка"),
    "hotkeys_short": ("F8 Pause · F9 Recenter", "F8 Пауза · F9 Центр"),
    "privacy": ("Camera frames stay on this computer", "Кадры обрабатываются на этом компьютере"),
    "privacy_no_clicks": (
        "Clicks disabled  ·  Camera frames stay on this computer",
        "Клики отключены  ·  Кадры обрабатываются на этом компьютере",
    ),
    "mode_camera_off": ("CAMERA OFF", "КАМЕРА ВЫКЛЮЧЕНА"),
    "mode_preview": ("PRACTICE  ·  SYSTEM MOUSE OFF", "ПРОБА  ·  СИСТЕМНАЯ МЫШЬ ВЫКЛЮЧЕНА"),
    "mode_input_off": ("SYSTEM MOUSE OFF", "СИСТЕМНАЯ МЫШЬ ВЫКЛЮЧЕНА"),
    "mode_active": ("SYSTEM MOUSE ON", "СИСТЕМНАЯ МЫШЬ ВКЛЮЧЕНА"),
    "status_welcome": (
        "Open the camera to try the pointer in practice mode.",
        "Откройте камеру, чтобы проверить управление в режиме пробы.",
    ),
    "status_opening": ("Opening the camera…", "Открываем камеру…"),
    "status_stopping": ("Turning off the camera…", "Камера выключается…"),
    "status_camera_off": ("Camera off. You can open it again.", "Камера выключена. Её можно открыть снова."),
    "status_paused": (
        "Paused. Select Enable mouse to resume control.",
        "Пауза. Чтобы снова управлять мышью, включите её кнопкой.",
    ),
    "status_recenter": (
        "Calibrating in place. Look straight ahead with both eyes open.",
        "Калибровка на месте. Смотрите прямо и откройте оба глаза.",
    ),
    "status_recenter_motion": ("Calibrating in place. Look straight ahead.", "Калибровка на месте. Смотрите прямо."),
    "status_recenter_left": (
        "Calibrating in place. Look straight ahead with your left eye open.",
        "Калибровка на месте. Смотрите прямо и держите левый глаз открытым.",
    ),
    "status_recenter_right": (
        "Calibrating in place. Look straight ahead with your right eye open.",
        "Калибровка на месте. Смотрите прямо и держите правый глаз открытым.",
    ),
    "hint_calibrating": (
        "Calibration {progress}% · Look straight ahead and keep both eyes open.",
        "Калибровка {progress}% · Смотрите прямо и держите оба глаза открытыми.",
    ),
    "hint_calibrating_motion": (
        "Calibration {progress}% · Look straight ahead and stay in view.",
        "Калибровка {progress}% · Смотрите прямо и держите лицо в кадре.",
    ),
    "hint_calibrating_left": (
        "Calibration {progress}% · Keep your left eye open and look straight ahead.",
        "Калибровка {progress}% · Смотрите прямо и держите левый глаз открытым.",
    ),
    "hint_calibrating_right": (
        "Calibration {progress}% · Keep your right eye open and look straight ahead.",
        "Калибровка {progress}% · Смотрите прямо и держите правый глаз открытым.",
    ),
    "hint_tracking": ("Face in view. Move your nose a little to steer.", "Лицо в кадре. Двигайте носом небольшими движениями."),
    "hint_wink": ("Wink detected. The pointer waits until you reopen your eye.", "Подмигивание. Точка ждёт, пока глаз откроется."),
    "hint_rearming": ("Keep both eyes open to continue.", "Держите оба глаза открытыми, чтобы продолжить."),
    "hint_rearming_motion": ("Keep your face in view to continue.", "Держите лицо в кадре, чтобы продолжить."),
    "hint_rearming_left": ("Open your left eye to continue.", "Откройте левый глаз, чтобы продолжить."),
    "hint_rearming_right": ("Open your right eye to continue.", "Откройте правый глаз, чтобы продолжить."),
    "hint_paused": ("Input paused while tracking is unavailable.", "Лицо потеряно или кадры задерживаются. Ввод приостановлен."),
    "safety_jump": ("Face moved suddenly. System control is off.", "Лицо резко сместилось. Управление выключено."),
    "safety_loss": ("Face out of view too long. System control is off.", "Лицо долго не было видно. Управление выключено."),
    "safety_stale_preview": (
        "Camera frames were delayed. Enable mouse again after calibration.",
        "Кадры задержались. Снова включите мышь после калибровки.",
    ),
    "safety_multiple": ("Multiple faces detected. System control is off.", "В кадре несколько лиц. Управление выключено."),
    "safety_pointer_moved": (
        "Click cancelled. The pointer is elsewhere. System control is off.",
        "Клик отменён. Указатель в другой точке. Управление выключено.",
    ),
    "safety_mouse_button": (
        "Click cancelled. A mouse button is held. System control is off.",
        "Клик отменён. Кнопка мыши удерживается. Управление выключено.",
    ),
    "safety_display_changed": (
        "Display layout changed. Enable mouse again after calibration.",
        "Расположение экранов изменилось. Снова включите мышь после калибровки.",
    ),
    "safety_control_busy": (
        "Another Nose Pointer window has mouse control. Pause it before enabling control here.",
        "Мышью управляет другое окно Nose Pointer. Поставьте его на паузу, затем включите управление здесь.",
    ),
    "safety_jump_brief": ("Face moved suddenly.", "Лицо резко сместилось."),
    "safety_loss_brief": ("Face out of view too long.", "Лицо долго не было видно."),
    "safety_stale_preview_brief": ("Camera frames were delayed.", "Кадры задержались."),
    "safety_multiple_brief": ("Multiple faces detected.", "В кадре несколько лиц."),
    "safety_pointer_moved_brief": ("Click cancelled because the pointer moved.", "Клик отменён. Указатель переместился."),
    "safety_mouse_button_brief": ("Click cancelled. A mouse button is held.", "Клик отменён. Кнопка мыши удерживается."),
    "safety_display_changed_brief": ("Display layout changed.", "Расположение экранов изменилось."),
    "safety_control_busy_brief": ("Another window has mouse control.", "Мышью управляет другое окно."),
    "instruction_wink": ("Wink with one eye, then reopen it.", "Подмигните одним глазом и откройте его."),
    "instruction_motion": ("Move the dot with your nose. Clicks are disabled.", "Двигайте точку носом. Клики отключены."),
    "instruction_dwell": ("Move the pointer, then hold it still to left-click.", "Переместите точку, затем задержитесь для левого клика."),
    "instruction_dwell_left": (
        "Keep your left eye open. Move the pointer and hold it still to click.",
        "Держите левый глаз открытым. Переместите указатель и задержитесь для клика.",
    ),
    "instruction_dwell_right": (
        "Keep your right eye open. Move the pointer and hold it still to click.",
        "Держите правый глаз открытым. Переместите указатель и задержитесь для клика.",
    ),
    "right_armed": ("Next click is right. Move to your target.", "Следующий клик — правый. Переместите указатель к цели."),
    "right_cancelled": ("Right click cancelled.", "Правый клик отменён."),
    "gesture_active_left": ("System mouse  ·  Left click", "Системная мышь  ·  Левый клик"),
    "gesture_active_right": ("System mouse  ·  Right click", "Системная мышь  ·  Правый клик"),
    "gesture_preview_left": ("Practice  ·  Left click", "Проба  ·  Левый клик"),
    "gesture_preview_right": ("Practice  ·  Right click", "Проба  ·  Правый клик"),
    "input_stopped": ("Input stopped. {detail}", "Ввод остановлен. {detail}"),
    "input_stopped_brief": ("System input stopped.", "Системный ввод остановлен."),
    "camera_error": ("Camera stopped with an error.", "Камера завершила работу с ошибкой."),
    "camera_error_detail": ("Camera error. {detail}", "Ошибка камеры. {detail}"),
    "camera_unavailable": (
        "Could not open the camera. Try another camera number or check permissions and other apps.",
        "Камеру открыть не удалось. Попробуйте другой номер камеры или проверьте разрешения и другие приложения.",
    ),
    "camera_unavailable_brief": ("Could not open the camera.", "Камеру открыть не удалось."),
    "camera_no_frames": ("The camera stopped sending frames.", "Камера перестала передавать кадры."),
    "model_verify_failed": ("Model verification failed.", "Проверка загруженной модели не прошла."),
    "model_missing": (
        "Model missing or damaged. Run setup with --download-model.",
        "Модель отсутствует или повреждена. Запустите настройку с --download-model.",
    ),
    "model_missing_brief": ("Tracking model missing or damaged.", "Модель распознавания отсутствует или повреждена."),
    "model_blank_face": ("A face was detected in the blank test image.", "На пустом тестовом кадре обнаружилось лицо."),
    "model_ready": ("Model ready.", "Модель готова."),
    "model_check_ok": (
        "Model check passed. The camera stayed off.",
        "Модель и обработка кадров работают. Камера оставалась выключенной.",
    ),
    "cli_description": (
        "Hands-free webcam pointer for Windows with a practice mode and emergency pause.",
        "Управление указателем Windows через веб-камеру с режимом пробы и экстренной паузой.",
    ),
    "cli_hotkeys": (
        "Tap F8 in Nose Pointer to pause. Hold F8 briefly in other windows. "
        "With mouse control enabled, tap F9 here to recalibrate or hold it briefly in another window.",
        "Нажмите F8 в окне Nose Pointer для паузы. В другом окне ненадолго удерживайте F8. "
        "При включённом управлении нажмите F9 в приложении для калибровки или ненадолго удерживайте клавишу в другом окне.",
    ),
    "cli_lang": ("interface language for this launch", "язык интерфейса для этого запуска"),
    "cli_help": ("show this help message and exit", "показать справку и завершить работу"),
    "cli_download": ("download and verify the local model", "скачать и проверить локальную модель"),
    "cli_check": ("run the model on a blank image with the camera off", "проверить модель на пустом изображении без камеры"),
    "cli_camera": ("webcam index for this launch (saved number or 0 by default)",
                   "номер веб-камеры для этого запуска (по умолчанию сохранённый номер или 0)"),
    "cli_range_x": ("horizontal nose displacement from center to screen edge", "смещение носа по горизонтали от центра до края экрана"),
    "cli_range_y": ("vertical nose displacement from center to screen edge", "смещение носа по вертикали от центра до края экрана"),
    "cli_wink": ("minimum intentional wink duration in milliseconds", "минимальная длительность подмигивания в миллисекундах"),
    "cli_no_mirror": ("reverse horizontal direction", "изменить направление по горизонтали"),
    "cli_swap": ("exchange left and right wink actions", "поменять местами левый и правый клики подмигиванием"),
    "cli_no_clicks": ("enable pointer motion only", "включить только движение указателя"),
    "cli_dwell": ("start in dwell mode with a 600–5000 ms delay", "открыть режим задержки с интервалом от 600 до 5000 мс"),
    "cli_dwell_invalid": ("Dwell delay must be between 600 and 5000 ms.", "Задержка клика должна быть от 600 до 5000 мс."),
    "cli_dwell_eye": (
        "start in dwell mode and select which eyes must stay open for this launch",
        "запустить режим задержки и указать, какие глаза держать открытыми в этом сеансе",
    ),
    "cli_dwell_eye_conflict": (
        "Choose --dwell-eye for dwell clicks or --no-clicks for motion only.",
        "Выберите --dwell-eye для кликов по задержке или --no-clicks только для движения.",
    ),
    "cli_platform": ("System input is supported on Windows.", "Системный ввод поддерживается в Windows."),
    "cli_camera_invalid": ("Camera index must be between 0 and 2147483647.",
                           "Индекс камеры должен быть от 0 до 2147483647."),
}


def translate(language, key, **fields):
    english, russian = MESSAGES[key]
    return (russian if language == "ru" else english).format(**fields)


def load_language():
    saved = read_preference("language", 5)
    return "ru" if saved in (b"ru", b"ru\n", b"ru\r\n") else "en"


def save_language(language):
    if language in LANGUAGES:
        save_preference("language", language)
