import os
import sys
import time
import threading
import subprocess
import whisper

# Поддерживаемые расширения аудио/видео файлов
SUPPORTED_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav", ".webm", ".ogg"}


def get_duration(file_path):
    """
    Получает длительность файла (в секундах) через ffprobe.
    Возвращает значение типа float или None, если не удалось определить длительность.
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format=duration', '-of',
             'default=noprint_wrappers=1:nokey=1', file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        return None


def collect_input_files(user_input, default_dir):
    """
    Определяет, что введено пользователем:
      - Если пустая строка, использует каталог по умолчанию.
      - Если введён путь к файлу или каталогу, использует его.
      - Если список путей через запятую – собирает их.
    Возвращает список полных путей к файлам с поддерживаемыми расширениями.
    """
    files = []
    user_input = user_input.strip()
    if not user_input:
        path = default_dir
        if os.path.isdir(path):
            for fname in os.listdir(path):
                full_path = os.path.join(path, fname)
                if os.path.isfile(full_path) and os.path.splitext(full_path)[1].lower() in SUPPORTED_EXTENSIONS:
                    files.append(full_path)
        elif os.path.isfile(path):
            files.append(path)
    else:
        # Если введён путь, проверяем, файл или каталог
        if os.path.isdir(user_input):
            for fname in os.listdir(user_input):
                full_path = os.path.join(user_input, fname)
                if os.path.isfile(full_path) and os.path.splitext(full_path)[1].lower() in SUPPORTED_EXTENSIONS:
                    files.append(full_path)
        elif os.path.isfile(user_input):
            files.append(user_input)
        else:
            # Предполагаем, что это список через запятую
            parts = [p.strip() for p in user_input.split(",") if p.strip()]
            for part in parts:
                if os.path.isdir(part):
                    for fname in os.listdir(part):
                        full_path = os.path.join(part, fname)
                        if os.path.isfile(full_path) and os.path.splitext(full_path)[1].lower() in SUPPORTED_EXTENSIONS:
                            files.append(full_path)
                elif os.path.isfile(part):
                    files.append(part)
    return files


def transcribe_file(model, input_file, lang, result_container):
    """Функция для транскрипции файла в отдельном потоке.
       Результат сохраняется в словаре result_container под ключом 'result'."""
    if lang:
        result = model.transcribe(input_file, language=lang)
    else:
        result = model.transcribe(input_file)
    result_container['result'] = result


def main():
    # Пути по умолчанию – измените при необходимости
    default_input_dir = ''
    default_output_dir = ''

    # Запрос входных файлов или каталога
    user_input = input(
        f"Введите путь к файлам (один файл, список через запятую или каталог) или нажмите Enter для использования каталога по умолчанию ({default_input_dir}): "
    )
    input_files = collect_input_files(user_input, default_input_dir)
    if not input_files:
        print("Не найдено корректных входных файлов.")
        return

    print("Будут обработаны следующие файлы:")
    for f in input_files:
        print(f)

    # Запрос выходной папки
    output_dir = input(
        f"\nВведите путь к выходной папке или нажмите Enter для использования каталога по умолчанию ({default_output_dir}): "
    ).strip()
    if not output_dir:
        output_dir = default_output_dir
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nВыходная папка: {output_dir}\n")# Список моделей и их описания
    models = ["tiny", "base", "small", "medium", "large"]
    descriptions = {
        "tiny":   "Очень быстрый, но с меньшей точностью",
        "base":   "Быстрый, чуть лучше, чем tiny",
        "small":  "Хороший баланс скорости и точности",
        "medium": "Медленнее, но обеспечивает улучшенное качество",
        "large":  "Самый медленный, но обеспечивает наивысшую точность"
    }
    print("Доступные модели:")
    for idx, model_name in enumerate(models, start=1):
        print(f"{idx}. {model_name} - {descriptions[model_name]}")
    model_choice = input("Введите номер выбранной модели (по умолчанию 1): ").strip()
    try:
        index = int(model_choice) - 1 if model_choice else 0
        chosen_model = models[index]
    except (ValueError, IndexError):
        print("Неверный ввод, используется модель 'tiny'.")
        chosen_model = "tiny"
    print(f"Выбрана модель: {chosen_model} - {descriptions[chosen_model]}")

    # Запрос языка (если оставить пустым – автоопределение)
    lang = input("Введите код языка (например, ru) или нажмите Enter для автоопределения: ").strip()
    if not lang:
        lang = None

    print("\nЗагрузка модели...", flush=True)
    model = whisper.load_model(chosen_model)
    print("Модель загружена.", flush=True)

    # КОэффициент, позволяющий оценить примерное время обработки.
    # Например, если scale_factor=4, то предполагается, что транскрипция займёт примерно 4 раза больше времени, чем длительность файла.
    scale_factor = 4

    # Обработка каждого файла
    for idx, input_file in enumerate(input_files, start=1):
        print(f"\nОбработка файла {idx} из {len(input_files)}: {input_file}", flush=True)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}.txt")

        # Получаем длительность файла через ffprobe (если ffprobe установлен и доступен)
        duration = get_duration(input_file)
        if duration:
            # Предполагаемое общее время обработки (в секундах)
            total_processing_time = duration * scale_factor
        else:
            total_processing_time = None

        # Результат транскрипции будет храниться здесь
        result_container = {}

        # Запускаем транскрипцию в отдельном потоке
        transcribe_thread = threading.Thread(target=transcribe_file, args=(model, input_file, lang, result_container))
        start_time = time.time()
        transcribe_thread.start()

        # Пока поток работает, выводим прогресс (по времени и процентам, если известна длительность)
        while transcribe_thread.is_alive():
            elapsed = time.time() - start_time
            if total_processing_time:
                percent = min(int((elapsed / total_processing_time) * 100), 99)
            else:
                percent = 0
            sys.stdout.write(f"\rОбработка файла: {os.path.basename(input_file)} | Время: {int(elapsed)} сек | Готово: {percent}%")
            sys.stdout.flush()
            time.sleep(1)
        transcribe_thread.join()
        sys.stdout.write("\rОбработка файла завершена!                     \n")
        sys.stdout.flush()

        # Получаем результат транскрипции
        result = result_container.get("result", {})
        transcript_text = result.get("text", "")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        print(f"\nРезультат для файла {input_file} сохранён в: {output_file}", flush=True)
        print("Транскрипция:", flush=True)
        print(transcript_text, flush=True)

    print("\nВсе файлы обработаны.", flush=True)


if __name__ == "__main__":
    main()

