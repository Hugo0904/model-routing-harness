/* Win32-only test payload. No CRT, credentials, provider calls, or capabilities.
 * Build with a native Windows C compiler; only kernel32 is statically imported.
 * Network mode sends no application data. All canaries are test-owned.
 */
#include <windows.h>
void *memset(void *target, int value, SIZE_T size) {
    unsigned char *p=target; while(size--)*p++=(unsigned char)value; return target;
}

static void number(const char *label, DWORD value) {
    char text[64], reverse[16]; int n=0, i=0, j=0; DWORD written;
    while (label[i]) { text[i]=label[i]; i++; }
    do { reverse[n++]=(char)('0'+value%10); value/=10; } while (value);
    while (n) text[i++]=reverse[--n];
    text[i++]='\n'; WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),text,i,&written,NULL);
}

static void files(void) {
    static WCHAR path[32768]; HANDLE file; DWORD result;
    GetEnvironmentVariableW(L"MRH_LPAC_CANARY",path,32768);
    file=CreateFileW(path,GENERIC_READ,7,NULL,OPEN_EXISTING,0,NULL);
    result=file==INVALID_HANDLE_VALUE?GetLastError():0;
    if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
    number("outside_read=",result);
    file=CreateFileW(path,GENERIC_WRITE,7,NULL,OPEN_EXISTING,0,NULL);
    result=file==INVALID_HANDLE_VALUE?GetLastError():0;
    if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
    number("outside_write=",result);
    GetModuleFileNameW(NULL,path,32768);
    file=CreateFileW(path,GENERIC_WRITE,7,NULL,OPEN_EXISTING,0,NULL);
    result=file==INVALID_HANDLE_VALUE?GetLastError():0;
    if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
    number("image_write=",result);
    file=CreateFileW(L"allowed.txt",GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL);
    result=file==INVALID_HANDLE_VALUE?GetLastError():0;
    if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
    number("inside_write=",result);
    number("secret_inherited=",GetEnvironmentVariableW(L"MRH_LPAC_SECRET_CANARY",path,32768)>0);
}

static void children(void) {
    static WCHAR path[32768], command[32768]; STARTUPINFOW si={0}; PROCESS_INFORMATION pi={0};
    DWORD i=0, j=0; HANDLE file; char pid[16]; int n=0, count; DWORD value,written;
    GetModuleFileNameW(NULL,path,32768);
    command[j++]='"'; while(path[i])command[j++]=path[i++];command[j++]='"';command[j]=0;
    SetEnvironmentVariableW(L"MRH_LPAC_TEST_CASE",L"sleep");
    si.cb=sizeof(si);
    if(!CreateProcessW(path,command,NULL,NULL,FALSE,DETACHED_PROCESS,NULL,NULL,&si,&pi)) {
        number("create_error=",GetLastError()); ExitProcess(10);
    }
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);
    value=pi.dwProcessId;
    do {pid[n++]=(char)('0'+value%10);value/=10;}while(value);
    for(i=0;i<n/2;i++){char t=pid[i];pid[i]=pid[n-1-i];pid[n-1-i]=t;}
    file=CreateFileW(L"pid",GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL);
    if(file==INVALID_HANDLE_VALUE){number("pid_error=",GetLastError());ExitProcess(11);}
    WriteFile(file,pid,n,&written,NULL);CloseHandle(file);
    number("child=",pi.dwProcessId);
    Sleep(30000);
}

static void network(void) {
    HMODULE module=LoadLibraryW(L"ws2_32.dll"); char data[512];
    int (WINAPI *startup)(WORD,void*); UINT_PTR (WINAPI *socket_)(int,int,int);
    int (WINAPI *connect_)(UINT_PTR,const void*,int); int (WINAPI *error_)(void);
    int (WINAPI *close_)(UINT_PTR); int code; UINT_PTR socket;
    struct {USHORT family,port;ULONG address;char zero[8];} address={2,0xbb01,0x01010101,{0}};
    if(!module){number("load_error=",GetLastError());return;}
    startup=(void*)GetProcAddress(module,"WSAStartup");socket_=(void*)GetProcAddress(module,"socket");
    connect_=(void*)GetProcAddress(module,"connect");error_=(void*)GetProcAddress(module,"WSAGetLastError");
    close_=(void*)GetProcAddress(module,"closesocket");
    code=startup(0x202,data);number("startup=",code);if(code)return;
    socket=socket_(2,1,6);code=socket==(UINT_PTR)-1?error_():0;number("socket=",code);if(code)return;
    code=connect_(socket,&address,sizeof(address));number("connect=",code==-1?error_():0);close_(socket);
}

static void hold(void) {
    char digits[16];int n=0,i;DWORD value=GetCurrentProcessId(),written;HANDLE file;
    do{digits[n++]=(char)('0'+value%10);value/=10;}while(value);
    for(i=0;i<n/2;i++){char t=digits[i];digits[i]=digits[n-1-i];digits[n-1-i]=t;}
    file=CreateFileW(L"pid",GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL);
    if(file==INVALID_HANDLE_VALUE)ExitProcess(11);
    WriteFile(file,digits,n,&written,NULL);CloseHandle(file);
    number("pid=",GetCurrentProcessId());Sleep(30000);
}

void _start(void) {
    WCHAR mode[32]; DWORD written; int i;
    GetEnvironmentVariableW(L"MRH_LPAC_TEST_CASE",mode,32);
    if(lstrcmpW(mode,L"files")==0)files();
    else if(lstrcmpW(mode,L"children")==0)children();
    else if(lstrcmpW(mode,L"sleep")==0)Sleep(30000);
    else if(lstrcmpW(mode,L"hold")==0)hold();
    else if(lstrcmpW(mode,L"network")==0)network();
    else if(lstrcmpW(mode,L"output")==0)for(i=0;i<10000;i++)WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),"xxxxxxxxxx\n",11,&written,NULL);
    ExitProcess(0);
}
/* TinyCC 0.9.27 emits ASLR relocations only for DLL output. The test builder
 * converts that relocatable image into an EXE with _start as its entry point. */
BOOL WINAPI _dllstart(HINSTANCE instance, DWORD reason, LPVOID reserved) { return TRUE; }
void (*lpac_relocation_anchor)(void) = _start;
