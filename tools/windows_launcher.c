#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(
    HINSTANCE instance,
    HINSTANCE previous_instance,
    PWSTR command_line,
    int show_command
) {
    wchar_t root[MAX_PATH];
    wchar_t python_path[MAX_PATH];
    wchar_t main_path[MAX_PATH];
    wchar_t child_command[MAX_PATH * 3];
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    wchar_t *separator;

    (void)instance;
    (void)previous_instance;
    (void)command_line;
    (void)show_command;

    if (GetModuleFileNameW(NULL, root, MAX_PATH) == 0) {
        MessageBoxW(NULL, L"无法定位小u程序目录。", L"小u", MB_OK | MB_ICONERROR);
        return 1;
    }
    separator = wcsrchr(root, L'\\');
    if (separator == NULL) {
        MessageBoxW(NULL, L"小u程序路径不正确。", L"小u", MB_OK | MB_ICONERROR);
        return 1;
    }
    *separator = L'\0';

    _snwprintf(
        python_path,
        MAX_PATH,
        L"%ls\\runtime\\pythonw.exe",
        root
    );
    _snwprintf(main_path, MAX_PATH, L"%ls\\main.py", root);
    _snwprintf(
        child_command,
        MAX_PATH * 3,
        L"\"%ls\" \"%ls\"",
        python_path,
        main_path
    );

    startup.cb = sizeof(startup);
    if (!CreateProcessW(
            python_path,
            child_command,
            NULL,
            NULL,
            FALSE,
            CREATE_UNICODE_ENVIRONMENT,
            NULL,
            root,
            &startup,
            &process
        )) {
        MessageBoxW(
            NULL,
            L"无法启动小u。请确认 runtime 文件夹与 XiaoU.exe 放在一起。",
            L"小u",
            MB_OK | MB_ICONERROR
        );
        return 1;
    }

    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
