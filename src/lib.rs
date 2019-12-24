use std::cell::RefCell;
use std::ffi::CStr;
use std::os::raw::c_char;

mod callstack;

thread_local!(static IN_THIS_LIBRARY: RefCell<bool> = RefCell::new(false));

/// Run the given function in such way that later calls to malloc() are handled
/// normally without being captured. Otherwise malloc() calls from this Rust
/// library trigger more Rust code, leading to infinite recursion, multiple
/// borrows, and other unpleasantness.
///
/// Basically: only call given function if we're being called directly from
/// outside world.
fn call_if_external_api(call: Box<dyn FnOnce() -> ()>) {
    IN_THIS_LIBRARY.with(|in_this_library| {
        if !*in_this_library.borrow() {
            *in_this_library.borrow_mut() = true;
            call();
            *in_this_library.borrow_mut() = false;
        }
    });
}

// Return current process memory usage. procinfo-based is much much faster than
// sysinfo-based, but Linux-only for now.
fn get_memory_usage() -> usize {
    let result = procinfo::pid::statm_self();
    match result {
        Ok(statm) => statm.resident * page_size::get(),
        Err(_) => {
            println!("Couldn't find current process?! This is a bug.");
            std::process::exit(1)
        },
    }
}

/// Do the necessary bookkeeping to update memory usage for current function on
/// stack.
/// TODO for current function in stack and all parents, maybe_set_new_peak().
fn update_memory_usage_while_in_malloc() {
    call_if_external_api(Box::new(|| {
        let memory = get_memory_usage();
        println!("Memory usage: {}", memory);
        callstack::update_memory_usage(memory);
    }));
}

// Override functions via C ABI, for LD_PRELOAD purposes.
// TODO: add calloc, realloc, posix_memalign. Probably not mmap?
redhook::hook! {
    unsafe fn malloc(size: libc::size_t) -> *mut libc::c_void => my_malloc {
        let result = redhook::real!(malloc)(size);
        update_memory_usage_while_in_malloc();
        result
    }
}

#[no_mangle]
pub extern "C" fn pymemprofile_start_call(name: *const c_char) {
    let name = unsafe {
        CStr::from_ptr(name).to_str().expect(
            "Function name wasn't UTF-8").to_string()
    };
    call_if_external_api(Box::new(move || {
        callstack::start_call(name, get_memory_usage());
    }));
}

#[no_mangle]
pub extern "C" fn pymemprofile_finish_call() {
    call_if_external_api(Box::new(|| {
        callstack::finish_call();
    }));
}

#[no_mangle]
pub extern "C" fn pymemprofile_dump_functions_to_flamegraph_svg(path: *const c_char) {
    let path = unsafe {
        CStr::from_ptr(path).to_str().expect("Path wasn't UTF-8").to_string()
    };
    call_if_external_api(Box::new(|| {
        callstack::dump_functions_to_flamegraph_svg(path);
        // TODO: Error handling?
    }));
}