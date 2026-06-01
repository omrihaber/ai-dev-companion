use std::env;

fn main() {
    // BUG: unwrap() panics if no argument is provided
    let arg = env::args().nth(1).unwrap();
    // BUG: unwrap() panics on non-numeric / out-of-range input
    let n: u8 = arg.parse().unwrap();
    // BUG: u8 arithmetic can overflow (panics in debug, wraps in release)
    let doubled = n * 2;
    println!("doubled = {}", doubled);
}
