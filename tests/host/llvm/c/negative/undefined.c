// Tests undefined symbol error
// SHOULD_FAIL: undefined symbol: some_unreal_symbol

extern void some_unreal_symbol();

void _start() {
    some_unreal_symbol();
}
