/* PriceMonitor UI localization. The application keeps English as its internal
   protocol language; this layer translates rendered UI text and attributes. */
(() => {
  'use strict';

  const STORAGE_KEY = 'price-monitor-v5.language';
  const RU = {
    'UTC MARKET INTELLIGENCE': 'АНАЛИТИКА РЫНКА UTC',
    'Interface language': 'Язык интерфейса',
    'Marketplace-only intelligence · all sellers, selected shop views.': 'Мониторинг через маркетплейсы · все продавцы и выбранные магазины.',
    'Starting services…': 'Запуск сервисов…',
    'Startup error': 'Ошибка запуска',
    'STEP 1': 'ШАГ 1', 'STEP 2': 'ШАГ 2', 'STEP 3': 'ШАГ 3',
    'Setup': 'Настройка',
    'Import stock to enroll models automatically': 'Импортируйте склад — модели добавятся в мониторинг автоматически',
    'Additional models (optional)': 'Дополнительные модели (необязательно)',
    'Stock → monitoring automatically': 'Склад → автоматическое добавление в мониторинг',
    'Loading…': 'Загрузка…', 'Import XLSX': 'Импорт XLSX',
    'Choose file': 'Выбрать файл', 'No file selected': 'Файл не выбран',
    'Download example workbook': 'Скачать пример файла',
    'Position management': 'Управление позициями',
    'Edit recognized items, pause monitoring or move items to the trash.': 'Редактируйте распознанные позиции, приостанавливайте мониторинг или переносите их в корзину.',
    'SOURCE': 'МОНИТОРИНГ', 'STOCK': 'СКЛАД',
    'Monitoring models': 'Модели для мониторинга', 'Warehouse stock': 'Складские позиции',
    'Clear table': 'Очистить таблицу', '+ Add': '+ Добавить',
    'Search models…': 'Поиск моделей…', 'Item, model or warehouse…': 'Позиция, модель или склад…',
    'States': 'Состояния', 'Model': 'Модель', 'Section': 'Раздел', 'Status': 'Статус', 'Actions': 'Действия',
    'Item / model': 'Позиция / модель', 'Stock': 'Склад',
    'Monitoring': 'Мониторинг',
    'Choose marketplaces to query and shops to display. Retailer sites are never queried.': 'Выберите маркетплейсы для проверки и магазины для отображения. Сайты магазинов напрямую не запрашиваются.',
    'Checking browser extensions…': 'Проверка расширений браузеров…',
    'Polite mode · one request per shop · loading policy…': 'Бережный режим · один запрос на источник · загрузка настроек…',
    'Marketplaces': 'Маркетплейсы', 'Comparison platforms': 'Площадки сравнения цен',
    'All marketplaces': 'Все маркетплейсы', 'Shops': 'Магазины',
    'Seller filters across marketplace offers': 'Фильтры продавцов в предложениях маркетплейсов',
    'All shops': 'Все магазины', 'No shops configured yet.': 'Магазины пока не настроены.',
    'Advanced settings': 'Расширенные настройки', 'Price cache': 'Кеш цен',
    'Up to 12 hours': 'До 12 часов', 'Up to 4 hours': 'До 4 часов',
    '· fresh checks': '· свежие проверки',
    'Fresh check · no cache': 'Свежая проверка · без кеша',
    'Start monitoring': 'Начать мониторинг', 'Clear current table?': 'Очистить текущую таблицу?',
    'Results and pending verification requests in this run will be removed.': 'Результаты и ожидающие ручные проверки этого прогона будут удалены.',
    'Cancel': 'Отмена', '■ Hard stop': '■ Жёсткая остановка',
    'Retry options': 'Настройки перепроверки', 'Marketplace': 'Маркетплейс',
    'Batch size': 'Размер пакета', '5 checks': '5 проверок', '10 checks': '10 проверок',
    '25 checks': '25 проверок', 'All matching checks': 'Все подходящие проверки',
    'Retry Salidzini only': 'Перепроверить только Salidzini',
    'Test Salidzini session': 'Проверить сессию Salidzini',
    'Review required checks': 'Проверить вручную', 'Ready.': 'Готово.',
    'Export table to Excel': 'Выгрузить таблицу в Excel',
    'Models': 'Модели', 'Statuses': 'Статусы', 'Columns': 'Столбцы',
    'Start monitoring to view results.': 'Запустите мониторинг, чтобы увидеть результаты.',
    'HISTORY': 'ИСТОРИЯ', 'Monitoring runs': 'Прогоны мониторинга', 'Refresh': 'Обновить',
    'Loading previous runs…': 'Загрузка предыдущих прогонов…', 'Exports': 'Выгрузки',
    'Latest activity': 'Последние события',
    'New item': 'Новая позиция', 'Edit item': 'Редактирование позиции', 'Close': 'Закрыть',
    'For example, 55P7L': 'Например, 55P7L',
    'Copy the model name to the clipboard': 'Скопировать название модели в буфер обмена',
    'Product categories': 'Категории товаров',
    'Select where this model belongs: televisions, soundbars or monitors. These categories match the Excel workbook sheets.': 'Укажите тип модели: телевизор, саундбар или монитор. Категории соответствуют листам Excel.',
    'Soundbars': 'Саундбары', 'Direct shop links': 'Прямые ссылки магазинов',
    '(optional overrides)': '(необязательная замена)',
    'Marketplace comparison links': 'Ссылки на страницы сравнения маркетплейсов',
    '(optional product-page overrides)': '(необязательные ссылки на товар)',
    'Item name': 'Название позиции', 'Item from the stock workbook': 'Позиция из складского файла',
    'Linked model': 'Связанная модель', 'Select or enter a model': 'Выберите или введите модель',
    'Warehouse': 'Склад', 'Main warehouse': 'Основной склад', 'Quantity': 'Количество',
    'Unit cost, EUR': 'Себестоимость, EUR', 'Pause monitoring': 'Приостановить мониторинг',
    'Save': 'Сохранить', 'BROWSER VERIFICATION': 'ПРОВЕРКА В БРАУЗЕРЕ',
    'Action required': 'Требуется действие',
    'Open & collect opens a dedicated marketplace tab. Complete CAPTCHA if shown; collection resumes automatically. The tab closes only after a complete result is saved. Partial or ambiguous results stay open for review. Open only keeps the manual workflow. Each card is one marketplace check.': 'Open & collect открывает отдельную вкладку маркетплейса. Если появится CAPTCHA, пройдите её — сбор продолжится автоматически. Вкладка закроется только после сохранения полного результата. Частичные или неоднозначные результаты останутся открытыми для проверки. Open only сохраняет ручной сценарий. Каждая карточка — отдельная проверка маркетплейса.',
    'Later': 'Позже', 'RESULT CORRECTION': 'ИСПРАВЛЕНИЕ РЕЗУЛЬТАТА',
    'Add / edit seller offer': 'Добавить / изменить предложение продавца',
    'Correct price, EUR': 'Правильная цена, EUR', 'Availability': 'Наличие',
    'Availability unknown': 'Наличие неизвестно', 'In stock': 'В наличии',
    'Pre-order': 'Предзаказ', 'Out of stock': 'Нет в наличии',
    'Seller / shop': 'Продавец / магазин', 'Seller name': 'Название продавца',
    'Product link': 'Ссылка на товар', '(required evidence)': '(обязательное подтверждение)',
    'Edit the selected offer, or add another seller. Marketplace links only. Manual decisions remain visible on future runs.': 'Измените выбранное предложение или добавьте другого продавца. Допустимы только ссылки маркетплейсов. Ручные решения будут видны в следующих прогонах.',
    'I reviewed all seller offers on this comparison page': 'Я проверил все предложения продавцов на этой странице сравнения',
    'Mark not found': 'Отметить как не найдено', 'Save seller offer': 'Сохранить предложение',
    'SAFE DIAGNOSTIC': 'БЕЗОПАСНАЯ ДИАГНОСТИКА', 'Test collection method': 'Проверка метода сбора',
    'Runs one method for one model. It does not start a full monitoring run or automatically try every method.': 'Запускает один метод для одной модели. Полный мониторинг и автоматический перебор методов не запускаются.',
    'Monitoring model': 'Модель мониторинга', 'Collection method': 'Метод сбора',
    'Choose a model and run the diagnostic.': 'Выберите модель и запустите диагностику.',
    'Run one test': 'Запустить один тест', 'Clear table?': 'Очистить таблицу?',
    'All active and paused rows in this table will move to Trash, including rows hidden by filters. Restore them using States → Trash. Monitoring results and run history are kept.': 'Все активные и приостановленные строки таблицы, включая скрытые фильтрами, будут перемещены в корзину. Их можно восстановить через Состояния → Корзина. Результаты мониторинга и история прогонов сохранятся.',
    'Move all to Trash': 'Переместить всё в корзину',

    'Quick · reuse complete automatic marketplace results for up to 12 hours. Mode changes cache age only, not collection methods.': 'Быстрый · использовать полные автоматические результаты до 12 часов. Режим меняет только возраст кеша, а не методы сбора.',
    'Balanced · reuse complete automatic marketplace results for up to 4 hours. Manual decisions are not reused as fresh prices. Mode changes cache age only.': 'Сбалансированный · использовать полные автоматические результаты до 4 часов. Ручные решения не используются как свежие цены. Режим меняет только возраст кеша.',
    'Deep · ignore the price cache and check again. The same collection methods and protection cooldowns still apply.': 'Глубокий · игнорировать кеш цен и проверить заново. Методы сбора и паузы защиты остаются прежними.',
    'Auto · gentle fallback': 'Авто · бережный резервный метод', 'Direct request': 'Прямой запрос',
    'Background Edge': 'Фоновый Edge', 'Playwright Edge': 'Playwright Edge',
    'Browser extension': 'Расширение браузера', 'Manual discovery · saved links auto': 'Ручной поиск · сохранённые ссылки автоматически',
    'Auto': 'Авто', 'Manual': 'Вручную', 'Legacy engine': 'Старый движок',
    'Assisted · Edge + manual': 'С поддержкой · Edge + вручную',
    'Enabled and available for the normal workflow.': 'Включено и доступно для обычной работы.',
    'Temporarily excluded from monitoring without deleting the position.': 'Временно исключено из мониторинга без удаления позиции.',
    'Moved to trash. It is excluded until restored or permanently deleted.': 'Перемещено в корзину и исключено до восстановления или окончательного удаления.',
    'This stock model is linked to an active model in the monitoring list.': 'Эта складская модель связана с активной моделью мониторинга.',
    'This stock position is not linked to an active monitoring model.': 'Эта складская позиция не связана с активной моделью мониторинга.',
    'An exact model match returned a usable price and a link to the offer.': 'Точное совпадение модели вернуло корректную цену и ссылку на предложение.',
    'The check ended with an error and returned no reliable result.': 'Проверка завершилась ошибкой и не вернула надёжный результат.',
    'The source was checked, but no matching model or offer was found.': 'Источник проверен, но подходящая модель или предложение не найдены.',
    'The check was stopped or could not finish with a reliable result.': 'Проверка остановлена или не смогла завершиться с надёжным результатом.',
    'A person must verify the page, retry capture, or confirm the result manually.': 'Нужно проверить страницу, повторить сбор или подтвердить результат вручную.',
    'Requests to this source are paused temporarily to avoid a longer block.': 'Запросы к источнику временно приостановлены, чтобы избежать длительной блокировки.',
    'A recent saved result was reused; no new retailer request was sent.': 'Использован недавний результат; новый запрос продавцу не отправлялся.',
    'A recent marketplace observation was reused. Its original collection time is preserved.': 'Повторно использовано недавнее наблюдение маркетплейса. Исходное время сбора сохранено.',
    'The check is currently running.': 'Проверка выполняется.', 'The check is queued and has not finished yet.': 'Проверка поставлена в очередь и ещё не завершена.',
    'This check has not started.': 'Проверка ещё не запущена.', 'This source is switched off and is not included in monitoring.': 'Источник выключен и не участвует в мониторинге.',
    'The completed marketplace pages did not list this shop. This does not mean the shop has no stock.': 'На полностью проверенных страницах маркетплейсов этот магазин не указан. Это не означает, что товара нет на складе магазина.',
    'Not verified: one or more marketplace checks are pending, blocked, stopped or incomplete. This is NOT Not found; no conclusion about this shop is possible yet.': 'Не проверено: одна или несколько проверок ожидают, заблокированы, остановлены или не завершены. Это НЕ статус «Не найдено» — вывод по магазину пока сделать нельзя.',
    'Seller filter · no direct requests': 'Фильтр продавца · без прямых запросов',
    'Comparison pages only': 'Только страницы сравнения', 'Collection': 'Сбор',
    'Extension not connected · Salidzini Auto needs the extension; manual entry remains available': 'Расширение не подключено · для Salidzini Авто требуется расширение; ручной ввод доступен',
    'Browser extension status unavailable': 'Статус расширения браузера недоступен',
    'Collection method updated.': 'Метод сбора обновлён.',
    'Ready to run one isolated request path.': 'Готово к запуску одного изолированного метода.',
    'Add an active monitoring model first.': 'Сначала добавьте активную модель мониторинга.',
    'Testing…': 'Проверка…', 'Opening one collection path. This can take up to the configured browser timeout.': 'Запускается один метод сбора. Это может занять время до установленного тайм-аута браузера.',
    'There is no model name to copy.': 'Нет названия модели для копирования.',
    'Item updated.': 'Позиция обновлена.', 'Item added.': 'Позиция добавлена.',
    'Restore': 'Восстановить', 'Delete permanently': 'Удалить навсегда', 'Edit': 'Изменить',
    'Resume': 'Возобновить', 'Pause': 'Приостановить', 'Trash': 'Корзина',
    'Active': 'Активно', 'Paused': 'Приостановлено', 'Unmatched': 'Не сопоставлено',
    'In monitoring': 'В мониторинге', 'Add to monitoring': 'Добавить в мониторинг',
    'No linked model': 'Нет связанной модели', 'No warehouse': 'Склад не указан',
    'No positions found.': 'Позиции не найдены.', 'No options': 'Нет вариантов',
    'Lithuania': 'Литва', 'Latvia': 'Латвия', 'Estonia': 'Эстония',
    'Marketplace min price': 'Минимальная цена маркетплейсов', 'Marketplace max price': 'Максимальная цена маркетплейсов',
    'Lowest in-stock': 'Минимальная цена в наличии', 'Lowest pre-order': 'Минимальная цена предзаказа',
    'How this marketplace is collected': 'Как происходит сбор информации',
    'Search TCL + model, then read current seller rows on the Kaina24 comparison page. Cash price and per-seller availability are read separately; delivery, installments, duplicate ads and sold-out history are excluded. Senukai uses its displayed SMART NET loyalty price. Saved comparison links are tried first. No retailer pages are opened; protection pauses requests.': 'Поиск выполняется по TCL + модели, затем на странице Kaina24 считываются актуальные строки продавцов. Денежная цена и наличие у продавца определяются отдельно; доставка, рассрочка, дубли объявлений и архивные распроданные товары исключаются. Для Senukai используется отображаемая цена лояльности SMART NET. Сначала используются сохранённые ссылки на сравнение. Сайты магазинов напрямую не открываются; защита сайта временно ставит запросы на паузу.',
    'Search TCL + model and read seller offers on the matching comparison page. One timeout is retried automatically. S45HE/S45H, S55HE/S55H and Q75HE/Q75H are explicit aliases; false prefix candidates are rejected and plausible variants go to Quick Review. Delivery time alone does not confirm stock. No retailer pages are opened.': 'Поиск выполняется по TCL + модели, затем считываются предложения продавцов на подходящей странице сравнения. Один тайм-аут повторяется автоматически. S45HE/S45H, S55HE/S55H и Q75HE/Q75H — подтверждённые варианты; ложные совпадения по префиксу исключаются, а правдоподобные варианты направляются в быструю проверку. Срок доставки не подтверждает наличие. Сайты магазинов не открываются.',
    'Auto uses one active Chrome or Edge extension at a time. A safe browser cycle checks 5, pauses, checks 5, pauses, then checks 10. CAPTCHA or two blank pages starts a protective cooldown; use Test Salidzini session before continuing or switch to the connected standby browser. No parallel requests, CAPTCHA solving or retailer-page visits.': 'Авто использует только одно активное расширение Chrome или Edge. Безопасный цикл проверяет 5 страниц, делает паузу, проверяет ещё 5, снова делает паузу, затем проверяет 10. CAPTCHA или две пустые страницы запускают защитную паузу; перед продолжением используйте проверку сессии Salidzini или переключитесь на подключённый резервный браузер. Параллельных запросов, решения CAPTCHA и посещения сайтов магазинов нет.',
    ' On every marketplace, if the original SKU is not found, search again with one, then two trailing characters removed (minimum 3 characters, letters and digits). Known S45HE/S45H, S55HE/S55H and Q75HE/Q75H aliases are accepted; other plausible variants go to Quick Review. Unrelated prefix matches are rejected.': ' На каждом маркетплейсе при отсутствии исходного SKU поиск повторяется с удалением одного, затем двух последних символов. Пары S45HE/S45H, S55HE/S55H и Q75HE/Q75H принимаются как подтверждённые варианты; другие правдоподобные варианты идут в быструю проверку, а посторонние совпадения по префиксу исключаются.',
    'Margin': 'Маржа', 'No monitoring results yet.': 'Результатов мониторинга пока нет.',
    'Success': 'Успешно', 'Failed': 'Ошибка', 'Not found': 'Не найдено',
    'Incomplete': 'Не завершено', 'Cooldown': 'Пауза', 'Cached': 'Из кеша',
    'Pending': 'Ожидание', 'Running': 'Выполняется', 'Not started': 'Не запущено',
    'Not listed': 'Не указан', 'Unverified': 'Не проверено',
    'Edit offer': 'Изменить предложение', 'Remove false match': 'Удалить ложное совпадение',
    'Page coverage complete': 'Страница проверена полностью',
    'Partial coverage — min/max reflect captured in-stock offers only': 'Неполное покрытие — минимум/максимум учитывают только собранные предложения в наличии',
    'Partial coverage — min/max reflect captured exact offers only': 'Неполное покрытие — минимум/максимум учитывают только собранные точные предложения',
    'No reliable offers yet.': 'Надёжных предложений пока нет.', 'Queued': 'В очереди',
    'Marketplace observations only. The retailer was not queried.': 'Только наблюдения маркетплейсов. Сайт магазина не запрашивался.',
    'Coverage incomplete — more offers may exist.': 'Покрытие неполное — могут существовать другие предложения.',
    'No captured offers from this seller.': 'Предложения этого продавца не собраны.',
    'Add seller offer / review': 'Добавить предложение / проверить',
    'Retry automatic check': 'Повторить автоматическую проверку', 'Wait & retry automatically': 'Подождать и повторить автоматически',
    'Capture again': 'Собрать повторно', 'Quick Review · choose the matching product': 'Быстрая проверка · выберите подходящий товар',
    'Remember this SKU alias for future runs': 'Запомнить этот вариант SKU для следующих прогонов',
    'Keyboard: 1/2 selects a candidate, 0 marks Not found. No price is accepted until you choose.': 'Клавиши: 1/2 выбирают вариант, 0 отмечает «Не найдено». Цена не принимается без вашего выбора.',
    'Undo last decision': 'Отменить последнее решение', 'Collected offers accepted in Quick Review': 'Собранные предложения приняты в быстрой проверке',
    'These links are suggestions, not confirmed SKU matches.': 'Эти ссылки — подсказки, а не подтверждённые совпадения SKU.',
    'Browser verification is required before this price can be collected.': 'Перед сбором цены требуется проверка в браузере.',
    'Open & collect': 'Открыть и собрать', 'Open only': 'Только открыть',
    'Confirm not found?': 'Подтвердить отсутствие?', 'This saves a final Not found result for this source.': 'Для этого источника будет сохранён окончательный результат «Не найдено».',
    'Confirm': 'Подтвердить', 'Save manual price': 'Сохранить цену вручную', 'Price, EUR': 'Цена, EUR',
    'Seller shown on the marketplace': 'Продавец, указанный на маркетплейсе', 'Save price': 'Сохранить цену',
    'Add product link': 'Добавить ссылку на товар', 'Product or search URL': 'Ссылка на товар или поиск',
    'The link is saved to this SKU and parsed now. Future checks try it first.': 'Ссылка сохраняется для SKU и обрабатывается сейчас. Следующие проверки сначала используют её.',
    'Save and parse': 'Сохранить и обработать', 'No checks currently require browser verification.': 'Сейчас нет проверок, требующих действий в браузере.',
    'Opening…': 'Открытие…', 'Capturing…': 'Сбор…', 'Scheduling…': 'Планирование…', 'Parsing…': 'Обработка…', 'Saving…': 'Сохранение…',
    'The selected check is capturing again.': 'Выбранная проверка собирается повторно.', 'Candidate selected and being collected.': 'Вариант выбран и собирается.', 'Collected offers accepted.': 'Собранные предложения приняты.',
    'The check will retry automatically when the cooldown ends.': 'Проверка повторится автоматически после окончания паузы.',
    'Link saved. PriceMonitor is parsing it now.': 'Ссылка сохранена. PriceMonitor обрабатывает её.',
    'Manual result saved.': 'Ручной результат сохранён.', 'The selected result is no longer available.': 'Выбранный результат больше недоступен.',
    'Current result:': 'Текущий результат:', 'Previous manual decision:': 'Предыдущее ручное решение:', 'none': 'нет',
    'Result corrected to Not found.': 'Результат исправлен на «Не найдено».', 'Corrected price saved.': 'Исправленная цена сохранена.',
    'Table cleared.': 'Таблица очищена.', 'Monitoring sources': 'Проверка источников', 'Monitoring complete': 'Мониторинг завершён',
    'Stopped': 'Остановлено', 'Completed': 'Завершено', 'Opened': 'Открыт', 'Open run': 'Открыть прогон',
    'No monitoring runs yet.': 'Прогонов мониторинга пока нет.', 'Show older runs': 'Показать предыдущие прогоны', 'No exports yet.': 'Выгрузок пока нет.',
    'Exports are unavailable.': 'Выгрузки недоступны.', 'No activity yet.': 'Событий пока нет.', 'Activity log is unavailable.': 'Журнал событий недоступен.',
    'Clear monitoring models?': 'Очистить модели мониторинга?', 'Clear warehouse stock?': 'Очистить складские позиции?',
    'These models will be excluded from future monitoring. Warehouse stock stays unchanged.': 'Эти модели будут исключены из следующих прогонов. Складские позиции не изменятся.',
    'Warehouse rows will be removed from the active stock table. All monitoring models remain enabled, even when their stock is removed.': 'Строки будут удалены из активной складской таблицы. Все модели мониторинга останутся включены, даже если их складские позиции удалены.',
    'Marketplace-only · 1 request per marketplace at a time · 3 s Kaina/Hinnavaatlus · 12 s Salidzini · automatic protection pause · manual entry available': 'Только маркетплейсы · по одному запросу на площадку · Kaina/Hinnavaatlus 3 с · Salidzini 12 с · автоматическая защитная пауза · доступен ручной ввод',
    'Stop the current monitoring run immediately? Completed results will be kept.': 'Немедленно остановить текущий прогон? Завершённые результаты сохранятся.',
    'Remove this false match from the current run?': 'Удалить это ложное совпадение из текущего прогона?',
    'Delete this position permanently? This cannot be undone.': 'Удалить позицию навсегда? Это действие нельзя отменить.',
    'Monitoring stopped. You can start a new run.': 'Мониторинг остановлен. Можно начать новый прогон.',
    'Current monitoring table and verification requests were cleared.': 'Текущая таблица мониторинга и запросы проверки очищены.',
    'Excel export started. The summary is fitted to one printed page horizontally.': 'Выгрузка Excel началась. Итоговая таблица помещается по ширине на одну печатную страницу.',
    'Enter a valid non-negative price.': 'Введите корректную неотрицательную цену.',
    'Enter the seller shown on the marketplace.': 'Введите продавца, указанного на маркетплейсе.',
    'Enter the link supporting this corrected price.': 'Введите ссылку, подтверждающую исправленную цену.',
    'v5: only Kaina24, Salidzini and Hinnavaatlus are queried. Shop columns are derived from marketplace offers.': 'v5: запрашиваются только Kaina24, Salidzini и Hinnavaatlus. Столбцы магазинов формируются из предложений маркетплейсов.',
    'CAPTCHA or security check: open the marketplace and complete verification, or enter offers manually': 'CAPTCHA или проверка безопасности: откройте маркетплейс и пройдите проверку либо введите предложения вручную',
    'Manual mode: no background requests. Choose Open & collect for a one-click check, or Open only → Send to PriceMonitor to review offers yourself.': 'Ручной режим: фоновые запросы не выполняются. Выберите «Открыть и собрать» для проверки в один клик или «Только открыть» → Send to PriceMonitor для самостоятельной проверки.',
    'Automatic requests are cooling down. Manual offer entry and browser capture are available now.': 'Автоматические запросы на паузе. Сейчас доступны ручной ввод и сбор через браузер.',
    'Salidzini Auto paused this batch to protect the browser session after CAPTCHA or repeated unavailable pages. No request was sent for this SKU. Complete the CAPTCHA in the retained tab, then retry Salidzini in a batch of 5.': 'Автоматический пакет Salidzini приостановлен для защиты браузерной сессии после CAPTCHA или повторных недоступных страниц. Запрос по этому SKU не отправлялся. Пройдите CAPTCHA в сохранённой вкладке, затем повторите Salidzini пакетом из 5 позиций.',
    'Some offers/pages need review; displayed prices cover captured offers only': 'Некоторые предложения или страницы нужно проверить; показанные цены учитывают только собранные предложения',
    'No reliable seller offers extracted. Open this marketplace, capture the comparison page or add the offers manually.': 'Надёжные предложения продавцов не извлечены. Откройте маркетплейс, соберите страницу сравнения или добавьте предложения вручную.',
    'Complete the CAPTCHA in the same tab, then send the page again': 'Пройдите CAPTCHA в той же вкладке, затем отправьте страницу ещё раз',
    'No reliable offers for this SKU were extracted. Check the model and page, or use manual price entry': 'Надёжные предложения для этого SKU не извлечены. Проверьте модель и страницу или введите цену вручную',
    'Retry unresolved': 'Повторить незавершённые', 'Include Not found': 'Включить «Не найдено»',
    'A retry batch is already running': 'Пакет перепроверки уже выполняется',
    'Preparing the next marketplace check…': 'Подготовка следующей проверки маркетплейса…',
    'Starting check': 'Запуск проверки', 'Queued for marketplace check': 'Поставлено в очередь маркетплейса',
    'Network unavailable — moved to review; queue continues': 'Сеть недоступна — проверка отправлена на ручной разбор, очередь продолжается',
    'Needs review — continuing with the next check': 'Требуется проверка — переходим к следующей позиции',
    'Protection pause · no more automatic requests in this batch': 'Защитная пауза · в этом пакете больше не будет автоматических запросов',
    'Checking original SKU': 'Проверка исходного SKU', 'Reading marketplace page': 'Чтение страницы маркетплейса',
    'Classifying offers on page': 'Проверка предложений на странице'
  };

  const RU_RULES = [
    [/^v(.+) · marketplace engine ready$/, m => `v${m[1]} · движок маркетплейсов готов`],
    [/^(\d+) of (\d+) enabled$/, m => `${m[1]} из ${m[2]} включено`],
    [/^(\d+) of (\d+) seller filters enabled$/, m => `${m[1]} из ${m[2]} фильтров продавцов включено`],
    [/^Show (\d+) older runs$/, m => `Показать предыдущие прогоны (${m[1]})`],
    [/^ETA (.+)$/, m => `Осталось примерно ${m[1]}`],
    [/^Finished (\d+)\/(\d+) · waiting (\d+) · checking (\d+) · review (\d+)$/, m => `готово ${m[1]}/${m[2]} · ожидает ${m[3]} · проверяется ${m[4]} · ручная проверка ${m[5]}`],
    [/^(\d+) unresolved checks queued\.$/, m => `В очередь поставлено проверок: ${m[1]}.`],
    [/^Use ([12])$/, m => `Выбрать ${m[1]}`],
    [/^Accept (\d+) collected offers?$/, m => `Принять собранные предложения: ${m[1]}`],
    [/^Testing Salidzini with (.+)\.$/, m => `Проверка Salidzini на модели ${m[1]}.`],
    [/^Retrying shortened SKU: (.+)$/, m => `Повторный поиск сокращённого SKU: ${m[1]}`],
    [/^Reading marketplace page (\d+)$/, m => `Чтение страницы маркетплейса ${m[1]}`],
    [/^Classifying offers on page (\d+)$/, m => `Проверка предложений на странице ${m[1]}`],
    [/^Monitoring: (\d+) active, (\d+) paused · Stock: (\d+) active, (\d+) unmatched$/, m => `Мониторинг: ${m[1]} активно, ${m[2]} приостановлено · Склад: ${m[3]} активно, ${m[4]} не сопоставлено`],
    [/^(\d+) models · v5 catalog · stock auto-enrolled$/, m => `${m[1]} моделей · каталог v5 · склад добавляется автоматически`],
    [/^(\d+) models · (.+)$/, m => `${m[1]} моделей · ${m[2]}`],
    [/^(\d+) items · (\d+) linked to models$/, m => `${m[1]} позиций · ${m[2]} связано с моделями`],
    [/^(\d+) units$/, m => `${m[1]} шт.`],
    [/^Review required checks \((\d+)\)$/, m => `Проверить вручную (${m[1]})`],
    [/^Success (\d+)$/, m => `Успешно ${m[1]}`], [/^Failed (\d+)$/, m => `Ошибки ${m[1]}`],
    [/^Not found (\d+)$/, m => `Не найдено ${m[1]}`], [/^Action required (\d+)$/, m => `Требуется действие ${m[1]}`],
    [/^Cooldown (\d+)$/, m => `Пауза ${m[1]}`], [/^Cached (\d+)$/, m => `Из кеша ${m[1]}`], [/^Pending (\d+)$/, m => `Ожидание ${m[1]}`],
    [/^Checked (.+)$/, m => `Проверено ${m[1]}`],
    [/^· cache up to (\d+) hours$/, m => `· кеш до ${m[1]} часов`],
    [/^\[INFO\] v5: only Kaina24, Salidzini and Hinnavaatlus are queried\. Shop columns are derived from marketplace offers\.$/, () => '[INFO] v5: запрашиваются только Kaina24, Salidzini и Hinnavaatlus. Столбцы магазинов формируются из предложений маркетплейсов.'],
    [/^History unavailable: (.+)$/, m => `История недоступна: ${m[1]}`],
    [/^Test (.+)$/, m => `Проверка ${m[1]}`],
    [/^Enable (.+)$/, m => `Включить ${m[1]}`], [/^How (.+) parsing works$/, m => `Как работает сбор ${m[1]}`],
    [/^Add (.+) to monitoring$/, m => `Добавить ${m[1]} в мониторинг`],
    [/^Refresh (.+)$/, m => `Обновить ${m[1]}`],
    [/^(.+) · (\d+) captured offers$/, m => `${m[1]} · собрано предложений: ${m[2]}`],
    [/^(.+) checks could not connect to the Internet\.(.*)$/, m => `${m[1]} проверок не смогли подключиться к интернету.${m[2]}`],
    [/^Price warning: (\d+)% above the lowest collected price \((.+)\)\. Verify the exact model\.$/, m => `Предупреждение: цена на ${m[1]}% выше минимальной собранной цены (${m[2]}). Проверьте точную модель.`],
    [/^Price warning: (\d+)% below the next collected price \((.+)\)\. Verify the exact model\.$/, m => `Предупреждение: цена на ${m[1]}% ниже следующей собранной цены (${m[2]}). Проверьте точную модель.`],
    [/^Incomplete Salidzini coverage: (.+)\. Review remaining or ambiguous listings\.$/, m => `Неполное покрытие Salidzini: ${m[1]}. Проверьте оставшиеся или неоднозначные позиции.`],
    [/^Coverage notice: (.+)\. Min\/max prices use the exact offers collected during this check; this partial result is not reused from cache\.$/, m => `Информация об охвате: ${m[1]}. Минимальная и максимальная цены рассчитаны по точным предложениям, собранным во время этой проверки; неполный результат не используется повторно из кеша.`],
    [/^Shortened searches found possible model variants\.(.*)$/, m => `Сокращённый поиск нашёл возможные варианты модели.${m[1]}`],
    [/^Network connection failed before the marketplace could be read\.(.*)$/, m => `Не удалось подключиться к сети до чтения маркетплейса.${m[1]}`]
  ];

  const PHRASES = [
    ['marketplace checks', 'проверок маркетплейсов'], ['Coverage notice', 'Информация об охвате'], ['Action required', 'Требуется действие'],
    ['Not found', 'Не найдено'], ['Availability unknown', 'Наличие неизвестно'],
    ['Out of stock', 'Нет в наличии'], ['In stock', 'В наличии'], ['Pre-order', 'Предзаказ'],
    ['Monitoring…', 'Мониторинг…'], ['Success', 'Успешно'], ['Failed', 'Ошибки'],
    ['Cooldown', 'Пауза'], ['Cached', 'Из кеша'], ['Pending', 'Ожидание'],
    ['Complete', 'Завершено'], ['Balanced', 'Сбалансированный'], ['Quick', 'Быстрый'], ['Deep', 'Глубокий'],
    [' · checking ', ' · проверка '], [' · live channel', ' · активный канал'],
    [' · recovery polling', ' · резервный опрос'], [' extension connected', ' · расширение подключено'],
    [' · active', ' · активен'], [' · use', ' · использовать'], ['Safe Auto:', 'Бережный авто-режим:'],
    ['pages in this browser cycle', 'страниц в цикле этого браузера'], [' · cooldown until ', ' · пауза до '],
    [' · reported price', ' · заявленная цена'], ['availability unconfirmed', 'наличие не подтверждено'],
    [' · all visible offers collected; marketplace count differs', ' · все видимые предложения собраны; счётчик маркетплейса отличается'],
    [' · partial', ' · частично'], [' · cached', ' · из кеша'], [' · Loyalty price', ' · цена по карте лояльности'],
    ['time unavailable', 'время недоступно'], ['Previous manual:', 'Ранее вручную:'],
    ['Open search', 'Открыть поиск'], ['Open product', 'Открыть товар'],
    ['comparison or search…', 'сравнение или поиск…'], [' units', ' шт.']
  ];

  function language() {
    if (typeof location !== 'undefined') {
      const requested = new URLSearchParams(location.search).get('lang');
      if (requested === 'ru' || requested === 'en') return requested;
    }
    if (typeof localStorage === 'undefined') return 'en';
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'ru' || saved === 'en') return saved;
    return (typeof navigator !== 'undefined' && /^ru\b/i.test(navigator.language || '')) ? 'ru' : 'en';
  }

  function translateText(value, target = language()) {
    const input = String(value ?? '');
    if (target !== 'ru' || !input.trim()) return input;
    const leading = input.match(/^\s*/)[0];
    const trailing = input.match(/\s*$/)[0];
    let text = input.trim();
    if (RU[text]) return leading + RU[text] + trailing;
    for (const [pattern, replacement] of RU_RULES) {
      const match = text.match(pattern);
      if (match) return leading + replacement(match) + trailing;
    }
    for (const [english, russian] of PHRASES) text = text.split(english).join(russian);
    return leading + text + trailing;
  }

  // Some desktop browser hosts expose a CommonJS-like `module` object to page
  // scripts. Only take the test export path when there is no browser window.
  if (typeof window === 'undefined' && typeof module !== 'undefined' && module.exports) {
    module.exports = { translateText, RU, RU_RULES, PHRASES };
    return;
  }

  const current = language();
  const translating = new WeakSet();
  const attributes = ['title', 'placeholder', 'aria-label'];

  function translateNode(root) {
    if (current !== 'ru' || !root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      const parent = root.parentElement;
      if (!parent || ['SCRIPT', 'STYLE', 'TEXTAREA'].includes(parent.tagName)) return;
      const next = translateText(root.nodeValue, current);
      if (next !== root.nodeValue) { translating.add(root); root.nodeValue = next; }
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) {
      for (const name of attributes) {
        const value = root.getAttribute(name);
        if (value) {
          const next = translateText(value, current);
          if (next !== value) root.setAttribute(name, next);
        }
      }
    }
  }

  function translateElement(root) {
    if (current !== 'ru' || !root) return;
    translateNode(root);
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let node;
    while ((node = walker.nextNode())) translateNode(node);
  }

  function install() {
    document.documentElement.lang = current;
    document.querySelectorAll('[data-language]').forEach(button => {
      const active = button.dataset.language === current;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      button.addEventListener('click', () => {
        if (button.dataset.language === current) return;
        const next = button.dataset.language;
        try { localStorage.setItem(STORAGE_KEY, next); } catch {}
        const url = new URL(location.href);
        url.searchParams.set('lang', next);
        location.assign(url.toString());
      });
    });
    translateElement(document);
    if (current === 'ru') {
      new MutationObserver(mutations => {
        for (const mutation of mutations) {
          if (mutation.type === 'characterData') {
            if (translating.has(mutation.target)) { translating.delete(mutation.target); continue; }
            translateElement(mutation.target);
          } else {
            mutation.addedNodes.forEach(translateElement);
            if (mutation.type === 'attributes') translateElement(mutation.target);
          }
        }
      }).observe(document.documentElement, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:attributes});
    }
  }

  window.pmI18n = {
    language: current,
    locale: current === 'ru' ? 'ru-RU' : 'en-GB',
    t: value => translateText(value, current),
    translate: translateElement
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, {once:true});
  else install();
})();
