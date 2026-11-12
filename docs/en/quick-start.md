# SocioLibrary

[简体中文](../windows.md) · **English quick start** · [Back to overview](../../README.en.md)

SocioLibrary connects a local Zotero library with search, source-page navigation, reading notes, paper comparisons and research graphs. The application interface currently uses Chinese; the labels below help you find each setting.

## Install

Download a package from the [official release](https://github.com/Yoesher/SocioLibrary/releases/latest).

- **Windows 10 / 11 x64:** use the installer, or extract the full portable ZIP. Do not copy the executable by itself. Microsoft WebView2 Runtime may be required.
- **macOS 15+:** choose Apple silicon or Intel, extract the ZIP and move the app to Applications. Quit the previous version before replacing it. Mac packages are previews, are not Developer ID signed or notarized, and do not offer automatic replacement or scanned-page OCR. Intel does not include local semantic inference.

Packages are unsigned. Keep system protections enabled and compare SHA-256 values with the release notes.

## Connect Zotero

1. Start Zotero. In its advanced settings, allow other applications on this computer to communicate with Zotero.
2. Open **资料与设置** (Data and settings) in SocioLibrary. Under **连接 Zotero** (Connect Zotero), use **测试连接** (Test connection).
3. Choose the permitted PDF folders with **选择文件夹** (Choose folder), or enter one absolute folder path per line. This may be Zotero's storage directory or a directory containing linked attachments. Save with **保存设置** (Save settings).
4. Use **同步 Zotero** (Sync Zotero). Metadata, notes and annotations can be imported without permitting PDF folders; PDF text requires permission to read the corresponding files.

Import is read-only and uses Zotero's local interface, not the Zotero database. Original attachments are not moved. Later syncs reuse unchanged files and preserve locally saved research records.

## Search and read

Open **文献检索** (Literature search). Enter keywords or a research question; author and year are optional filters. Results group passages by paper and show source abstracts, query relevance and matching PDF pages. Open the corresponding page in Zotero to check the source.

Lexical search does not need a model. For semantic search, prepare the local model under **本地语义检索** (Local semantic search), then build an index. For a large collection, enter core Zotero collection names in **全文语义试点文件夹名称** (Full-text semantic pilot collections) before indexing. The Intel Mac preview supports lexical and bilingual word-expansion retrieval, not local semantic inference.

**推荐与比较** opens recommendations and structured comparisons. **Zotero 批注** lists imported PDF annotations. **文献关系图谱** opens the research graph: select a paper, expand its neighbors, pin positions, inspect relationship evidence and save a named view. Automatic links are reading leads that need checking.

## Optional AI

Use **AI 阅读与连接** (AI reading and connections) to configure your own API endpoint and credentials. The software does not include API credit. Preview and explicitly approve selected material before each request. AI answers and comparison drafts require source checks; they do not replace the original paper.

Credentials are stored locally. Local search does not need a hosted AI service. Journal discovery, model downloads, software updates and configured AI requests need an internet connection.

## Upgrade and keep your work

On Windows, open **软件更新** (Software updates). You may download first; installation waits for unsaved work and background operations to be handled. Alternatively, quit and run the new installer over the existing installation. On Mac, quit and replace the application manually.

Program files and research data are separate. The library, models, notes and settings are retained. A version change creates and checks a local database/settings snapshot before initialization. Large libraries may take several minutes. Windows shows startup stages and supports safe cancellation. Restarting the same version does not create another upgrade snapshot.

The actual research directory appears in **资料与设置**. Keep separate backups of original PDFs and the complete research directory. Do not restore an old database over an app that is running, and do not mix database files with unrelated WAL/SHM files.

## Help

[Open an issue](https://github.com/Yoesher/SocioLibrary/issues) with your operating system, version and steps to reproduce. Use synthetic examples and remove private papers, credentials and personal paths from logs. More detailed guides are currently [in Chinese](../README.md).
