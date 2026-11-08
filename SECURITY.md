# Безопасность и privacy

- Не коммитить config, credentials, environment files, backups, логи, кэш, outbox,
  заметки, скриншоты, модели, WAV или venv. `.gitignore` — дополнительная защита, не DLP.
- Не помещать secrets в URL, git remote или CLI arguments. Credential Manager —
  только namespace `JarvisVoiceAssistant.*`; не просматривать чужое хранилище.
- Runtime config/legacy fallback должны иметь ограниченный Windows ACL.
  Новый проект не переносит ACL/файлы/секреты работающего экземпляра автоматически.
- Raw phrases/replies могут попадать в runtime-log. Clipboard read/TTS приватны;
  clipboard translate/summary явно передают выбранный текст внешнему сервису.
- Не считать wake word/voice confirmation проверкой личности. Видео/чужой голос
  могут активировать устройство. Speaker verification не реализована.
- Локальное закрытие окна, screen lock, mute и shutdown имеют реальные последствия.
  Не включать assistant в недоверенной среде без собственного threat model.
- Server должен требовать chat confirmation для consequential actions, проверять
  permissions, обрабатывать text/clipboard как untrusted data и deduplicate request IDs.
- Outbox — только plain text для TTS. Никогда не исполнять его как Python/shell.
- Скачивать weights из доверенных источников; Torch packages могут исполнять код.
- Репозиторий рассчитан на private-first публикацию. Перед public повторить scan
  всего дерева **и истории**, включая author/committer metadata и remote URLs.
- `python scripts/scan_tree.py` (или `--staged` после git add) находит типовые patterns,
  но не доказывает отсутствие secrets и не анализирует сложную сборку строк.
  Для release дополнительно использовать gitleaks, если установлен, и ручное ревью.
  Тестовые dummy/fixture значения и названия credential-полей не являются реальными ключами.
- Если утёк настоящий secret: сначала отозвать/заменить его; удаление файла новым commit
  не стирает значение из Git history. History rewrite выполнять только с подтверждением владельца.
